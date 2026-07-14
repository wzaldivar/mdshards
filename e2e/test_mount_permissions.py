"""Regression: split bind mounts with host ownership must not lose writes.

The compose shape users actually write mounts the vault and cache
separately (`/host/vault:/data/vault`, `./cache:/data/cache`), leaving
`/data` itself as the image layer. The entrypoint's chown guard used to
check only `/data` — already owned by app — so the nested mounts kept
host ownership (NAS uid, docker-created root dirs), every flush raised
PermissionError inside the flush task where it was never retrieved, and
edits vanished silently behind a healthy-looking editor.

This journey seeds two root-owned volumes, boots the app with UID/GID
remap, edits through a real browser, and requires both the vault write
and the .yjs cache to land.
"""

import subprocess
from collections.abc import Iterator

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from conftest import APP_READY_LOG, click_editor, type_text, wait_vault_file

PERM_ALIAS = "mdshards-perms"
_VOLUMES = ("mdshards-e2e-perm-vault", "mdshards-e2e-perm-cache")


@pytest.fixture(scope="module")
def rootowned_app(app_image: str, network: Network) -> Iterator[DockerContainer]:
    for vol in _VOLUMES:
        subprocess.run(
            ["docker", "volume", "create", vol], check=True, capture_output=True
        )
    # Seed host-like ownership: vault owned by root with a preexisting note
    # (a NAS export / docker-created dir), cache root-owned and empty. The
    # app image itself provides the root shell — no extra image pull.
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{_VOLUMES[0]}:/v",
            "-v",
            f"{_VOLUMES[1]}:/c",
            "--entrypoint",
            "sh",
            app_image,
            "-c",
            'chown -R 0:0 /v /c && echo "# seeded by host" > /v/index.md && chown 0:0 /v/index.md',
        ],
        check=True,
        capture_output=True,
    )
    container = DockerContainer(app_image)
    container.with_network(network)
    container.with_network_aliases(PERM_ALIAS)
    container.with_env("UID", "1000")
    container.with_env("GID", "1000")
    container.with_volume_mapping(_VOLUMES[0], "/data/vault", "rw")
    container.with_volume_mapping(_VOLUMES[1], "/data/cache", "rw")
    container.waiting_for(
        LogMessageWaitStrategy(APP_READY_LOG).with_startup_timeout(60)
    )
    container.start()
    yield container
    container.stop()
    for vol in _VOLUMES:
        subprocess.run(
            ["docker", "volume", "rm", vol], check=False, capture_output=True
        )


def test_edits_flush_despite_host_owned_mounts(driver, rootowned_app):
    driver.get(f"http://{PERM_ALIAS}:8000/")
    click_editor(driver)
    marker = "perm-mount-roundtrip"
    type_text(driver, marker + " ")
    # the vault write must land...
    wait_vault_file(rootowned_app, "index.md", marker)
    # ...and the CRDT cache too (it was the first casualty of the root-owned
    # ./cache dir — and its failure used to take the vault flush down with it)
    code, _ = rootowned_app.exec(
        ["sh", "-c", "find /data/cache -name '*.yjs' | grep -q ."]
    )
    assert code == 0, "no .yjs cache file was written"
    # the entrypoint remapped ownership of both mounts
    code, out = rootowned_app.exec(
        ["stat", "-c", "%u:%g", "/data/vault", "/data/cache"]
    )
    assert code == 0 and out.decode().split() == ["1000:1000", "1000:1000"], out
