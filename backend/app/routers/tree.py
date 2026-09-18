import asyncio
import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, HTTPException, Request

from ..config import get_settings
from ..tree import build_tree

router = APIRouter(prefix="/api")

# Defense-in-depth controls for unbounded traversal DoS mitigation.
# Since the application has no authentication (see CLAUDE.md), these controls
# establish resource bounds and abuse throttling at the route level.

# Response cache: avoid repeated expensive traversals for identical requests.
# TTL balances freshness (vault changes must surface) with DoS resistance.
_CACHE_TTL_SECONDS = 5.0
_cache_lock = Lock()
_cached_tree: dict | None = None
_cache_timestamp: float = 0.0

# Build lock: prevent thundering herd on cache miss (only one build at a time).
_build_lock: asyncio.Lock | None = None


def _get_build_lock() -> asyncio.Lock:
    """Lazy-initialize the async build lock (can't create at module level)."""
    global _build_lock
    if _build_lock is None:
        _build_lock = asyncio.Lock()
    return _build_lock


# Per-client rate limiting: prevent a single source from monopolizing resources.
# Tracks request counts per client IP over a sliding window.
_RATE_LIMIT_WINDOW_SECONDS = 60.0
_RATE_LIMIT_MAX_REQUESTS = 30  # 30 requests per minute per IP
_rate_limit_lock = Lock()
_rate_limit_state: dict[str, list[float]] = defaultdict(list)

# Traversal bounds: limit the work and response size per request.
_MAX_TRAVERSAL_DEPTH = 20  # Prevent deep directory nesting attacks
_MAX_ENTRIES = 10000  # Cap total entries to bound memory and serialization cost

# Request timeout: prevent long-running traversals from tying up workers.
_TRAVERSAL_TIMEOUT_SECONDS = 10.0


def _get_client_ip(request: Request) -> str:
    """Extract client IP for rate limiting. Prefers X-Forwarded-For when behind
    a proxy, falls back to direct connection IP."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # X-Forwarded-For can be a comma-separated list; take the first (client).
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_rate_limit(client_ip: str) -> None:
    """Enforce per-client rate limit. Raises HTTPException(429) when exceeded."""
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS

    with _rate_limit_lock:
        # Prune stale timestamps outside the sliding window for this client.
        timestamps = _rate_limit_state[client_ip]
        _rate_limit_state[client_ip] = [ts for ts in timestamps if ts > cutoff]

        if len(_rate_limit_state[client_ip]) >= _RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: max {_RATE_LIMIT_MAX_REQUESTS} requests per {_RATE_LIMIT_WINDOW_SECONDS}s",
            )

        _rate_limit_state[client_ip].append(now)

        # Periodic cleanup: remove clients with no recent requests to prevent
        # unbounded memory growth. Only check occasionally to avoid overhead.
        if len(_rate_limit_state) > 1000 and now % 60 < 1:
            stale_clients = [
                ip
                for ip, ts_list in _rate_limit_state.items()
                if not ts_list or max(ts_list) < cutoff
            ]
            for ip in stale_clients:
                del _rate_limit_state[ip]


def _get_cached_tree() -> dict | None:
    """Return cached tree if still valid, else None."""
    with _cache_lock:
        if _cached_tree is None:
            return None
        age = time.time() - _cache_timestamp
        if age > _CACHE_TTL_SECONDS:
            return None
        return _cached_tree


def _set_cached_tree(tree: dict) -> None:
    """Store tree in cache with current timestamp."""
    global _cached_tree, _cache_timestamp
    with _cache_lock:
        _cached_tree = tree
        _cache_timestamp = time.time()


def _count_entries(node: dict, depth: int = 0) -> int:
    """Count total entries in tree and enforce depth limit."""
    if depth > _MAX_TRAVERSAL_DEPTH:
        raise HTTPException(
            status_code=500,
            detail=f"Traversal depth limit exceeded (max {_MAX_TRAVERSAL_DEPTH})",
        )
    count = 1
    for child in node.get("children", []):
        count += _count_entries(child, depth + 1)
        if count > _MAX_ENTRIES:
            raise HTTPException(
                status_code=500,
                detail=f"Entry count limit exceeded (max {_MAX_ENTRIES})",
            )
    return count


async def _build_tree_with_timeout() -> dict:
    """Build tree with timeout to prevent long-running traversals."""
    try:
        # Run the synchronous build_tree in a thread pool to avoid blocking.
        tree = await asyncio.wait_for(
            asyncio.to_thread(build_tree, get_settings().vault_dir),
            timeout=_TRAVERSAL_TIMEOUT_SECONDS,
        )
        # Validate bounds after construction.
        _count_entries(tree)
        return tree
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=500,
            detail=f"Tree traversal timeout (max {_TRAVERSAL_TIMEOUT_SECONDS}s)",
        )


@router.get("/tree")
async def get_tree(request: Request) -> dict:
    """Return the vault tree with DoS mitigation controls.

    Implements defense-in-depth against unbounded traversal attacks:
    - Response caching to reduce repeated expensive operations
    - Per-client rate limiting to prevent monopolization
    - Traversal depth and entry count limits to bound work
    - Request timeout to prevent worker starvation
    - Single-build-at-a-time to prevent thundering herd on cache miss

    These controls are necessary because the application has no authentication
    (see CLAUDE.md) and the route is network-accessible.
    """
    # Rate limiting: prevent a single client from monopolizing resources.
    client_ip = _get_client_ip(request)
    _check_rate_limit(client_ip)

    # Cache hit: return immediately without traversal.
    cached = _get_cached_tree()
    if cached is not None:
        return cached

    # Cache miss: acquire build lock to prevent thundering herd.
    # Only one request builds at a time; others wait and recheck cache.
    async with _get_build_lock():
        # Recheck cache after acquiring lock - another request may have built it.
        cached = _get_cached_tree()
        if cached is not None:
            return cached

        # Build tree with timeout and bounds enforcement.
        tree = await _build_tree_with_timeout()
        _set_cached_tree(tree)
        return tree
