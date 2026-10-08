#!/usr/bin/env python3
"""Store the AI provider API keys that the web UI submits.

The API cannot encrypt systemd credentials (that needs the host's root-only
credential secret), so it drops a one-shot request into its runtime directory
(``/run/bdencode-api``, tmpfs, mode 0700).  A systemd path unit starts this
helper as root whenever such a file exists.  The helper deletes every request
first, accepts only the fixed AI credential names, encrypts the key with
``systemd-creds encrypt`` (the key travels on stdin, never on a command line)
into the operator's credential directory, re-binds the API's credentials
exactly like the installer does and restarts the API so it loads them.

Outcomes, never keys, are written to
``/var/lib/bdencode/credentials/status.json``.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

API_UNIT = "bdencode-api.service"
# Must match ``api_credential_names`` in install/install.sh.
API_CREDENTIALS = ("tracker-aither-api-token", "openai-api-key", "anthropic-api-key")
SETTABLE = {"openai-api-key": "sk-", "anthropic-api-key": "sk-ant-"}
DROPIN_PATH = Path("/etc/systemd/system/bdencode-api.service.d/credential.conf")
STATUS_PATH = Path("/var/lib/bdencode/credentials/status.json")
REQUEST_GLOB = "credential-request-*.json"
MAX_REQUEST_BYTES = 4096
KEEP_RESULTS = 20
KEY_RE = re.compile(r"[A-Za-z0-9_\-]{20,400}")
REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}")

Runner = Callable[..., Any]


class RequestError(ValueError):
    """The request is unusable; nothing is changed."""


def _stamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def take_requests(directory: Path, uid: int) -> list[dict[str, Any] | RequestError]:
    """Read and delete every pending request; the API's own files only."""

    taken: list[dict[str, Any] | RequestError] = []
    try:
        names = sorted(os.listdir(directory))
    except FileNotFoundError:
        return taken
    for name in names:
        if not fnmatch.fnmatchcase(name, REQUEST_GLOB):
            continue
        path = directory / name
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            path.unlink(missing_ok=True)
            taken.append(RequestError("request cannot be opened"))
            continue
        try:
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                raw = handle.read(MAX_REQUEST_BYTES + 1)
        finally:
            path.unlink(missing_ok=True)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid:
            taken.append(RequestError("request is not a regular file of the API user"))
            continue
        if len(raw) > MAX_REQUEST_BYTES:
            taken.append(RequestError("request is too large"))
            continue
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            taken.append(RequestError("request is not valid JSON"))
            continue
        taken.append(document if isinstance(document, dict) else RequestError("request is not an object"))
    return taken


def validate(document: Mapping[str, Any]) -> tuple[str, str, str, str | None]:
    """(request id, credential, action, key) of a well-formed request."""

    if document.get("schema_version") != 1:
        raise RequestError("unsupported request")
    request_id = document.get("request_id")
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise RequestError("invalid request id")
    name = document.get("credential")
    if name not in SETTABLE:
        raise RequestError("this credential cannot be changed from the web UI")
    action = document.get("action")
    if action == "delete":
        if set(document) - {"schema_version", "request_id", "credential", "action"}:
            raise RequestError("unknown request fields")
        return request_id, name, action, None
    if action != "set" or set(document) - {"schema_version", "request_id", "credential", "action", "value"}:
        raise RequestError("invalid action")
    value = document.get("value")
    if not isinstance(value, str) or not KEY_RE.fullmatch(value) or not value.startswith(SETTABLE[name]):
        raise RequestError("the key has an invalid format")
    if name == "openai-api-key" and value.startswith("sk-ant-"):
        raise RequestError("the key has an invalid format")
    return request_id, name, action, value


def _checked_directory(directory: Path, uid: int) -> None:
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise RequestError("the credential directory must be the API user's own 0700 directory")


def store(directory: Path, name: str, value: str, uid: int, gid: int, run: Runner) -> None:
    _checked_directory(directory, uid)
    temporary = directory / f".{name}.cred.new"
    temporary.unlink(missing_ok=True)
    try:
        run(
            ["systemd-creds", "encrypt", f"--name={name}", "-", str(temporary)],
            input=value,
        )
        os.chown(temporary, uid, gid)
        os.chmod(temporary, 0o600)
        os.replace(temporary, directory / f"{name}.cred")
    finally:
        temporary.unlink(missing_ok=True)
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def remove(directory: Path, name: str, uid: int) -> None:
    _checked_directory(directory, uid)
    (directory / f"{name}.cred").unlink(missing_ok=True)


def render_dropin(directory: Path, uid: int, dropin: Path, run: Runner) -> list[str]:
    """Bind every valid API credential, as install.sh does; returns the names."""

    lines = ["[Service]"]
    bound: list[str] = []
    for name in API_CREDENTIALS:
        path = directory / f"{name}.cred"
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size == 0
            or info.st_uid != uid
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            continue
        try:
            run(["systemd-creds", "decrypt", f"--name={name}", str(path), "/dev/null"])
        except (OSError, subprocess.SubprocessError):
            continue
        lines.append(f"LoadCredentialEncrypted={name}:{path}")
        bound.append(name)
    if bound:
        temporary = dropin.with_name(f".{dropin.name}.new")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o644)
        os.replace(temporary, dropin)
    else:
        dropin.unlink(missing_ok=True)
    return bound


def write_status(path: Path, results: list[dict[str, Any]], bound: list[str] | None) -> None:
    try:
        previous = json.loads(path.read_text(encoding="utf-8")).get("results", [])
        if not isinstance(previous, list):
            previous = []
    except (OSError, ValueError, AttributeError):
        previous = []
    document: dict[str, Any] = {
        "schema_version": 1,
        "results": [*previous, *results][-KEEP_RESULTS:],
    }
    if bound is not None:
        document["bound"] = bound
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    # The unit runs with UMask=0077, which also masks mkdir's mode; the API
    # (not root) must be able to read the outcome.
    os.chmod(path.parent, 0o755)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def _default_run(argv: Sequence[str], input: str | None = None) -> Any:
    return subprocess.run(
        list(argv), check=True, capture_output=True, text=True, timeout=60, input=input
    )


def process(
    *,
    request_directory: Path,
    credential_directory: Path,
    user: str,
    dropin: Path = DROPIN_PATH,
    status_path: Path = STATUS_PATH,
    run: Runner = _default_run,
    ids: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    if ids is None:
        import pwd  # POSIX only; tests pass ``ids``

        account = pwd.getpwnam(user)
        ids = (account.pw_uid, account.pw_gid)
    uid, gid = ids
    results: list[dict[str, Any]] = []
    changed = False
    for item in take_requests(request_directory, uid):
        outcome: dict[str, Any] = {"state": "rejected", "finished_at": _stamp()}
        try:
            if isinstance(item, RequestError):
                raise item
            request_id, name, action, value = validate(item)
            outcome.update(request_id=request_id, credential=name, action=action)
            if action == "set":
                store(credential_directory, name, value or "", uid, gid, run)
            else:
                remove(credential_directory, name, uid)
            changed = True
            outcome.update(state="applied", message="saved; the API restarts to load it")
        except RequestError as exc:
            outcome["message"] = str(exc)
        except (OSError, subprocess.SubprocessError) as exc:
            # CalledProcessError names the command only; the key is on stdin.
            outcome.update(state="failed", message=f"{type(exc).__name__}: {exc}"[:300])
        outcome["finished_at"] = _stamp()
        results.append(outcome)
    bound: list[str] | None = None
    if changed:
        try:
            bound = render_dropin(credential_directory, uid, dropin, run)
            run(["systemctl", "daemon-reload"])
            run(["systemctl", "try-restart", API_UNIT])
        except (OSError, subprocess.SubprocessError) as exc:
            for outcome in results:
                if outcome["state"] == "applied":
                    outcome.update(
                        state="failed",
                        message=f"stored, but the API could not be restarted: {type(exc).__name__}"[:300],
                    )
    if results:
        write_status(status_path, results, bound)
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("process",))
    arguments = parser.parse_args(argv)
    environment = os.environ
    missing = [
        key
        for key in ("BDENCODE_USER", "BDENCODE_CREDENTIAL_DIR", "BDENCODE_CREDENTIAL_REQUEST_DIR")
        if not environment.get(key)
    ]
    if missing:
        print("missing environment: " + ", ".join(missing), file=sys.stderr)
        return 2
    results = process(
        request_directory=Path(environment["BDENCODE_CREDENTIAL_REQUEST_DIR"]),
        credential_directory=Path(environment["BDENCODE_CREDENTIAL_DIR"]),
        user=environment["BDENCODE_USER"],
    )
    print(json.dumps([{k: v for k, v in item.items() if k != "message"} for item in results]))
    return 0 if all(item["state"] == "applied" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
