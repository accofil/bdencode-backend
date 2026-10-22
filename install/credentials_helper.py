#!/usr/bin/env python3
"""Store the API keys that the web UI submits.

The API cannot encrypt systemd credentials (that needs the host's root-only
credential secret), so it drops a one-shot request into its runtime directory
(``/run/bdencode-api``, tmpfs, mode 0700).  A systemd path unit starts this
helper as root whenever such a file exists.  The helper deletes every request
first, accepts only fixed credential names, encrypts the key with
``systemd-creds encrypt`` (the key travels on stdin, never on a command line)
into the operator's credential directory and re-binds the consumer service's
credentials exactly like the installer does.

* The AI adviser keys belong to the API: the helper restarts the API so it
  loads them.
* The image host keys belong to the worker, which may be in the middle of an
  encode and is never restarted here.  Besides re-binding them for the next
  worker start, the helper publishes the change into the running worker's
  own runtime directory (``/run/bdencode-worker/credentials``, tmpfs, mode
  0700, removed by systemd when the worker stops): the new key, or an empty
  file for a deleted one.  The worker reads that copy at every upload.  It is
  the same exposure as systemd's own decrypted runtime credentials: plaintext
  on tmpfs, readable only by the service user.

Outcomes, never keys, are written to
``/var/lib/bdencode/credentials/status.json``.
"""

from __future__ import annotations

import argparse
import contextlib
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
# Must match ``worker_credential_names`` in install/install.sh and
# ``HOST_CREDENTIALS`` in src/bdencode/upload_settings.py.
WORKER_CREDENTIALS = ("imgbb-api-key", "catbox-userhash", "freeimage-api-key")
KEY_RE = re.compile(r"[A-Za-z0-9_\-]{20,400}")
# The credentials the web UI may change, with their accepted format; the
# upload host patterns must match HOST_KEY_PATTERNS in upload_settings.py.
SETTABLE: dict[str, re.Pattern[str]] = {
    "openai-api-key": KEY_RE,
    "anthropic-api-key": KEY_RE,
    "imgbb-api-key": re.compile(r"[A-Za-z0-9]{32}"),
    "freeimage-api-key": re.compile(r"[A-Za-z0-9]{32}"),
    "catbox-userhash": re.compile(r"[A-Za-z0-9]{16,64}"),
}
PREFIXES = {"openai-api-key": "sk-", "anthropic-api-key": "sk-ant-"}
DROPIN_PATH = Path("/etc/systemd/system/bdencode-api.service.d/credential.conf")
WORKER_DROPIN_PATH = Path("/etc/systemd/system/bdencode-worker.service.d/credential.conf")
# The worker unit's RuntimeDirectory; LIVE_SUBDIRECTORY inside it matches
# BDENCODE_LIVE_CREDENTIAL_DIR in deploy/systemd/bdencode-worker.service.in.
WORKER_RUNTIME_DIRECTORY = Path("/run/bdencode-worker")
LIVE_SUBDIRECTORY = "credentials"
STATUS_PATH = Path("/var/lib/bdencode/credentials/status.json")
REQUEST_GLOB = "credential-request-*.json"
MAX_REQUEST_BYTES = 4096
KEEP_RESULTS = 20
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
    if not isinstance(name, str) or name not in SETTABLE:
        raise RequestError("this credential cannot be changed from the web UI")
    action = document.get("action")
    if action == "delete":
        if set(document) - {"schema_version", "request_id", "credential", "action"}:
            raise RequestError("unknown request fields")
        return request_id, name, action, None
    if action != "set" or set(document) - {"schema_version", "request_id", "credential", "action", "value"}:
        raise RequestError("invalid action")
    value = document.get("value")
    if (
        not isinstance(value, str)
        or not SETTABLE[name].fullmatch(value)
        or not value.startswith(PREFIXES.get(name, ""))
    ):
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


def render_dropin(
    directory: Path,
    uid: int,
    dropin: Path,
    run: Runner,
    names: Sequence[str] = API_CREDENTIALS,
) -> list[str]:
    """Bind every valid credential of ``names``, as install.sh does; returns them."""

    lines = ["[Service]"]
    bound: list[str] = []
    for name in names:
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


def publish_live(
    runtime_directory: Path, name: str, value: str | None, uid: int, gid: int
) -> bool:
    """Hand a changed worker key to the running worker; False when none runs.

    ``value`` ``None`` writes an empty file: the key was deleted.  The runtime
    directory belongs to the worker user, so every step works on directory
    descriptors opened without following symlinks, and the file is replaced
    by a rename inside that directory (never written through a planted link).
    """

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    try:
        parent = os.open(runtime_directory, os.O_RDONLY | directory_flag | nofollow)
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(parent)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid:
            raise RequestError("the worker's runtime directory is not the worker user's own")
        try:
            os.mkdir(LIVE_SUBDIRECTORY, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
        live = os.open(LIVE_SUBDIRECTORY, os.O_RDONLY | directory_flag | nofollow, dir_fd=parent)
        try:
            info = os.fstat(live)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {uid, 0}:
                raise RequestError("the worker's key directory is not a directory of the worker user")
            os.fchown(live, uid, gid)
            os.fchmod(live, 0o700)
            temporary = f".{name}.new"
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=live)
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600, dir_fd=live
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write((value or "").encode("utf-8"))
                    handle.flush()
                    os.fchown(handle.fileno(), uid, gid)
                    os.fchmod(handle.fileno(), 0o600)
                os.replace(temporary, name, src_dir_fd=live, dst_dir_fd=live)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temporary, dir_fd=live)
                raise
        finally:
            os.close(live)
    finally:
        os.close(parent)
    return True


def write_status(
    path: Path,
    results: list[dict[str, Any]],
    bound: list[str] | None,
    worker_bound: list[str] | None = None,
) -> None:
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
    if worker_bound is not None:
        document["worker_bound"] = worker_bound
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
    worker_dropin: Path = WORKER_DROPIN_PATH,
    worker_runtime_directory: Path = WORKER_RUNTIME_DIRECTORY,
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
    api_changed: list[dict[str, Any]] = []
    # (outcome, credential, new value or None) of every applied worker change,
    # in request order: the last change of a name is the one the worker keeps.
    worker_changes: list[tuple[dict[str, Any], str, str | None]] = []
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
            if name in WORKER_CREDENTIALS:
                outcome.update(state="applied", message="saved; the worker uses it from its next upload")
                worker_changes.append((outcome, name, value if action == "set" else None))
            else:
                outcome.update(state="applied", message="saved; the API restarts to load it")
                api_changed.append(outcome)
        except RequestError as exc:
            outcome["message"] = str(exc)
        except (OSError, subprocess.SubprocessError) as exc:
            # CalledProcessError names the command only; the key is on stdin.
            outcome.update(state="failed", message=f"{type(exc).__name__}: {exc}"[:300])
        outcome["finished_at"] = _stamp()
        results.append(outcome)
    bound: list[str] | None = None
    worker_bound: list[str] | None = None
    if api_changed or worker_changes:
        try:
            if api_changed:
                bound = render_dropin(credential_directory, uid, dropin, run, API_CREDENTIALS)
            if worker_changes:
                worker_bound = render_dropin(
                    credential_directory, uid, worker_dropin, run, WORKER_CREDENTIALS
                )
            # Before the running worker hears of a change: a worker that starts
            # from now on loads the re-bound credentials.
            run(["systemctl", "daemon-reload"])
            if api_changed:
                run(["systemctl", "try-restart", API_UNIT])
        except (OSError, subprocess.SubprocessError) as exc:
            for outcome in results:
                if outcome["state"] == "applied":
                    outcome.update(
                        state="failed",
                        message=f"stored, but the services could not be updated: {type(exc).__name__}"[:300],
                    )
            worker_changes = []
        for outcome, name, value in worker_changes:
            try:
                running = publish_live(worker_runtime_directory, name, value, uid, gid)
            except (OSError, RequestError) as exc:
                outcome.update(
                    state="failed",
                    message=(
                        "stored for the next worker start, but the running worker "
                        f"could not take it: {type(exc).__name__}: {exc}"
                    )[:300],
                )
                continue
            if not running:
                outcome["message"] = "saved; the worker loads it when it starts"
    if results:
        write_status(status_path, results, bound, worker_bound)
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
