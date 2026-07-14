"""Real-browser end-to-end suite.

Everything the unit suites trust — resolve responses, CRDT frames, the
serve-time shell rewrite — is exercised here the way a user meets it: the
single-container image (the repo-root `Dockerfile`, the thing releases
ship) built and started via testcontainers, a `selenium/standalone-chromium`
container on the same Docker network, and Selenium driving that browser
against the app by its network alias. No mocks, no TestClient.

Requires a Docker daemon (colima locally, native on CI). The whole suite
skips cleanly when none is reachable.

Run from the repo root:  pytest e2e -v
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

REPO_ROOT = Path(__file__).resolve().parent.parent

# The browser reaches the app by these network aliases; the two app
# containers (root mount / sub-path mount) live side by side for the whole
# session so tests don't pay a container start per case.
ROOT_ALIAS = "mdshards-root"
SUBPATH_ALIAS = "mdshards-wiki"
SUBPATH_PREFIX = "/wiki"

APP_READY_LOG = "Uvicorn running"
SELENIUM_IMAGE = "selenium/standalone-chromium:latest"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=20)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="session", autouse=True)
def _require_docker() -> None:
    if not _docker_available():
        pytest.skip("Docker daemon not reachable — e2e suite needs one")


@pytest.fixture(scope="session")
def app_image() -> str:
    """Build the shipping image from the repo-root Dockerfile via the docker
    CLI — the Dockerfile uses `COPY --chmod`, which needs BuildKit, and the
    CLI enables it by default while docker-py (testcontainers' builder) does
    not. Layer cache makes repeat runs cheap; the first build compiles the
    frontend too."""
    tag = "mdshards:e2e"
    subprocess.run(
        ["docker", "build", "-t", tag, str(REPO_ROOT)],
        check=True,
        capture_output=True,
        timeout=900,
    )
    return tag


@pytest.fixture(scope="session")
def network() -> Iterator[Network]:
    with Network() as net:
        yield net


def _start_app(
    image: str, network: Network, alias: str, env: dict[str, str]
) -> DockerContainer:
    container = DockerContainer(image)
    container.with_network(network)
    container.with_network_aliases(alias)
    for key, value in env.items():
        container.with_env(key, value)
    container.waiting_for(
        LogMessageWaitStrategy(APP_READY_LOG).with_startup_timeout(60)
    )
    container.start()
    return container


@pytest.fixture(scope="session")
def root_app(app_image: str, network: Network) -> Iterator[DockerContainer]:
    """The app at a root mount (no BASE_URL) — deployment mode 1 verbatim."""
    container = _start_app(app_image, network, ROOT_ALIAS, {})
    yield container
    container.stop()


@pytest.fixture(scope="session")
def subpath_app(app_image: str, network: Network) -> Iterator[DockerContainer]:
    """The app mounted at /wiki. No proxy container needed: the backend
    accepts prefixed paths directly (ASGI root_path), which is exactly what
    a prefix-preserving proxy would forward."""
    container = _start_app(
        app_image, network, SUBPATH_ALIAS, {"BASE_URL": SUBPATH_PREFIX}
    )
    yield container
    container.stop()


@pytest.fixture(scope="session")
def selenium_url(network: Network) -> Iterator[str]:
    chrome = DockerContainer(SELENIUM_IMAGE)
    chrome.with_network(network)
    chrome.with_exposed_ports(4444)
    chrome.waiting_for(
        LogMessageWaitStrategy("Started Selenium").with_startup_timeout(120)
    )
    chrome.start()
    url = f"http://{chrome.get_container_host_ip()}:{chrome.get_exposed_port(4444)}"
    yield url
    chrome.stop()


@pytest.fixture
def driver(selenium_url: str) -> Iterator[WebDriver]:
    options = ChromeOptions()
    # The selenium image's Chromium runs in a container with a small
    # /dev/shm; this flag keeps renderers from crashing on media/pages.
    options.add_argument("--disable-dev-shm-usage")
    last_error: Exception | None = None
    for _ in range(5):
        try:
            d = webdriver.Remote(command_executor=selenium_url, options=options)
            break
        except Exception as e:  # grid may lag its own log line
            last_error = e
            time.sleep(2)
    else:
        raise RuntimeError(f"could not connect to Selenium: {last_error}")
    d.set_window_size(1400, 900)
    yield d
    d.quit()


# ---- shared helpers ----


def wait_for(driver: WebDriver, css: str, timeout: float = 20):
    return WebDriverWait(driver, timeout).until(
        lambda d: d.find_elements(By.CSS_SELECTOR, css) or False
    )[0]


def wait_until(driver: WebDriver, predicate, timeout: float = 20):
    return WebDriverWait(driver, timeout).until(lambda _: predicate() or None)


def editor_text(driver: WebDriver) -> str:
    els = driver.find_elements(By.CSS_SELECTOR, ".cm-content")
    return els[0].text if els else ""


def click_editor(driver: WebDriver) -> None:
    wait_for(driver, ".cm-content").click()


def type_text(driver: WebDriver, text: str) -> None:
    ActionChains(driver).send_keys(text).perform()


def read_vault_file(container: DockerContainer, rel_path: str) -> str | None:
    code, output = container.exec(["cat", f"/data/vault/{rel_path}"])
    return output.decode() if code == 0 else None


def wait_vault_file(
    container: DockerContainer,
    rel_path: str,
    contains: str,
    timeout: float = 20,
) -> str:
    """Poll the vault until `rel_path` exists on disk and contains the
    marker — the CRDT layer flushes asynchronously, so give it a moment."""
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        last = read_vault_file(container, rel_path)
        if last is not None and contains in last:
            return last
        time.sleep(0.5)
    raise AssertionError(
        f"vault file {rel_path!r} never contained {contains!r}; last read: {last!r}"
    )


def seed_vault_file(container: DockerContainer, rel_path: str, content: bytes) -> None:
    """Write a file into the vault as an EXTERNAL writer (the Syncthing/
    Obsidian role) — base64 through exec to survive arbitrary bytes."""
    import base64

    b64 = base64.b64encode(content).decode()
    parent = f"/data/vault/{rel_path}".rsplit("/", 1)[0]
    code, output = container.exec(
        [
            "sh",
            "-c",
            f"mkdir -p {parent} && echo {b64} | base64 -d > /data/vault/{rel_path}",
        ]
    )
    assert code == 0, output.decode()


# 1x1 red PNG — enough for the browser to decode and report naturalWidth > 0.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8cfc0500f00040501a04a968d21"
    "0000000049454e44ae426082"
)
