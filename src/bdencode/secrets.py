"""Secret loading with systemd credentials as the production default.

systemd hands a service its credentials once, at start.  A key changed on the
System page must reach a worker that is in the middle of an encode, so the
root helper (``install/credentials_helper.py``) also publishes the new value
into the worker's own runtime directory (``/run/bdencode-worker/credentials``,
tmpfs, mode 0700, removed by systemd when the worker stops).  That copy wins
over the start-time credential while it exists: a file with the key is the
new key, an empty file means the key was deleted.  After a worker restart the
directory is gone and systemd loads the re-bound encrypted credential.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Mapping

#: Set in the worker unit; the directory the root helper publishes changes to.
LIVE_CREDENTIAL_DIR_ENV = "BDENCODE_LIVE_CREDENTIAL_DIR"
MAX_LIVE_CREDENTIAL_BYTES = 4096
_CREDENTIAL_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class SecretUnavailable(RuntimeError):
    pass


def _read_live_secret(directory: Path, name: str) -> str | None:
    """The helper's newer value: ``None`` when it published none for ``name``."""

    if not _CREDENTIAL_NAME_RE.fullmatch(name):
        raise SecretUnavailable(f"invalid credential name: {name!r}")
    path = directory / name
    try:
        details = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise SecretUnavailable(f"the changed credential cannot be read: {name}") from exc
    if not stat.S_ISREG(details.st_mode):
        raise SecretUnavailable(f"invalid changed credential for {name}")
    try:
        raw = path.read_bytes()[: MAX_LIVE_CREDENTIAL_BYTES + 1]
        value = raw.decode("utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise SecretUnavailable(f"the changed credential cannot be read: {name}") from exc
    if len(raw) > MAX_LIVE_CREDENTIAL_BYTES:
        raise SecretUnavailable(f"invalid changed credential for {name}")
    return value


def read_secret(
    name: str,
    *,
    environment: Mapping[str, str] | None = None,
    allow_environment: bool = False,
) -> str:
    env = os.environ if environment is None else environment
    live_directory = env.get(LIVE_CREDENTIAL_DIR_ENV)
    if live_directory:
        live = _read_live_secret(Path(live_directory), name)
        if live is not None:
            if live:
                return live
            # Deleted on the System page: the start-time copy is stale.
            raise SecretUnavailable(f"credential was deleted: {name}")
    credentials_dir = env.get("CREDENTIALS_DIRECTORY")
    if credentials_dir:
        # systemd only exposes the credentials that were configured, so a
        # missing entry is an ordinary "not configured" answer that must reach
        # the caller's fallback path as SecretUnavailable, not a raw OSError.
        try:
            root = Path(credentials_dir).resolve(strict=True)
            target: Path | None = (root / name).resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            target = None
        if target is not None:
            if target.parent != root or not target.is_file():
                raise SecretUnavailable(f"invalid credential path for {name}")
            value = target.read_text(encoding="utf-8").strip()
            if value:
                return value
    if allow_environment:
        key = name.upper().replace("-", "_")
        if env.get(key):
            return env[key].strip()
    raise SecretUnavailable(f"credential is not available: {name}")
