from fastapi import APIRouter

from ..config import get_settings
from ..tree import build_tree

router = APIRouter(prefix="/api")


@router.get("/tree")
def get_tree() -> dict:
    return build_tree(get_settings().vault_dir)
