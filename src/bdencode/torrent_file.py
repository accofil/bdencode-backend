"""Private BitTorrent v1 files, without an external tool.

The trackers rewrite the announce URL and may change other info fields of an
uploaded torrent, so its info-hash can change.  ``same_content`` therefore
compares what identifies the data: name, file layout and piece hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import stat
from typing import Any, Callable

from . import __version__

MIN_PIECE_EXPONENT = 18  # 256 KiB
MAX_PIECE_EXPONENT = 26  # 64 MiB
# Far below the 1 MB limit of a .torrent file on the trackers.
TARGET_PIECES = 2800
READ_BYTES = 4 * 1024 * 1024


class TorrentError(ValueError):
    pass


def bencode(value: Any) -> bytes:
    if isinstance(value, bool):
        raise TorrentError("bencode has no boolean")
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode("utf-8")
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, (list, tuple)):
        return b"l" + b"".join(bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        items = sorted(
            (key.encode("utf-8") if isinstance(key, str) else key, item)
            for key, item in value.items()
        )
        return b"d" + b"".join(bencode(key) + bencode(item) for key, item in items) + b"e"
    raise TorrentError(f"bencode cannot encode {type(value).__name__}")


def _decode_at(data: bytes, position: int) -> tuple[Any, int]:
    try:
        marker = data[position : position + 1]
        if marker == b"i":
            end = data.index(b"e", position)
            return int(data[position + 1 : end]), end + 1
        if marker == b"l":
            items: list[Any] = []
            position += 1
            while data[position : position + 1] != b"e":
                item, position = _decode_at(data, position)
                items.append(item)
            return items, position + 1
        if marker == b"d":
            mapping: dict[bytes, Any] = {}
            position += 1
            while data[position : position + 1] != b"e":
                key, position = _decode_at(data, position)
                if not isinstance(key, bytes):
                    raise TorrentError("a bencoded key is not a string")
                mapping[key], position = _decode_at(data, position)
            return mapping, position + 1
        if marker.isdigit():
            colon = data.index(b":", position)
            start = colon + 1
            end = start + int(data[position:colon])
            if end > len(data):
                raise TorrentError("a bencoded string is cut short")
            return data[start:end], end
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, TorrentError):
            raise
        raise TorrentError("invalid bencoded data") from None
    raise TorrentError("invalid bencoded data")


def bdecode(data: bytes) -> Any:
    value, position = _decode_at(data, 0)
    if position != len(data):
        raise TorrentError("data follows the bencoded value")
    return value


def _raw_info(data: bytes) -> bytes:
    """The info dictionary's own bytes: re-encoding could change a foreign torrent's hash."""

    if data[:1] != b"d":
        raise TorrentError("a torrent is a bencoded dictionary")
    position = 1
    while data[position : position + 1] != b"e":
        key, position = _decode_at(data, position)
        start = position
        _value, position = _decode_at(data, position)
        if key == b"info":
            return data[start:position]
    raise TorrentError("the torrent has no info dictionary")


def info_hash(data: bytes) -> str:
    return hashlib.sha1(_raw_info(data), usedforsecurity=False).hexdigest()


def _info(data: bytes) -> dict[bytes, Any]:
    decoded = bdecode(data)
    info = decoded.get(b"info") if isinstance(decoded, dict) else None
    if not isinstance(info, dict) or not info.get(b"pieces"):
        raise TorrentError("the torrent has no usable info dictionary")
    return info


def _layout(info: dict[bytes, Any]) -> tuple[Any, ...]:
    files = info.get(b"files")
    if files is None:
        return (info.get(b"name"), info.get(b"length"))
    return (
        info.get(b"name"),
        tuple((tuple(item.get(b"path") or ()), item.get(b"length")) for item in files),
    )


def same_content(first: bytes, second: bytes) -> bool:
    """The same data, even when the tracker changed the source tag and so the hash."""

    try:
        left, right = _info(first), _info(second)
    except TorrentError:
        return False
    return (
        _layout(left) == _layout(right)
        and left.get(b"piece length") == right.get(b"piece length")
        and left.get(b"pieces") == right.get(b"pieces")
    )


def file_names(data: bytes) -> tuple[str, ...]:
    """The payload's files, relative to the save path, as a client would lay them out."""

    info = _info(data)
    name = info[b"name"].decode("utf-8")
    files = info.get(b"files")
    if files is None:
        return (name,)
    return tuple(
        "/".join((name, *(part.decode("utf-8") for part in item[b"path"]))) for item in files
    )


def piece_exponent(total_bytes: int) -> int:
    exponent = MIN_PIECE_EXPONENT
    while exponent < MAX_PIECE_EXPONENT and (total_bytes >> exponent) >= TARGET_PIECES:
        exponent += 1
    return exponent


@dataclass(frozen=True)
class BuiltTorrent:
    data: bytes
    info_hash: str
    piece_length: int
    piece_count: int
    total_bytes: int


def _content_files(content: Path) -> list[tuple[Path, tuple[str, ...]]]:
    details = content.lstat()
    if stat.S_ISREG(details.st_mode):
        return [(content, ())]
    if not stat.S_ISDIR(details.st_mode):
        raise TorrentError("the torrent content must be a regular file or a folder")
    found: list[tuple[Path, tuple[str, ...]]] = []
    for path in sorted(content.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise TorrentError(f"not a regular file in the torrent content: {path.name}")
        found.append((path, path.relative_to(content).parts))
    if not found:
        raise TorrentError("the torrent content is empty")
    return found


def build_torrent(
    content: Path,
    *,
    source: str,
    announce: str,
    progress: Callable[[int, int], None] | None = None,
) -> BuiltTorrent:
    """A private torrent of one file or one folder; ``progress`` gets (done, total) bytes."""

    files = _content_files(content)
    total = sum(path.stat().st_size for path, _parts in files)
    if total <= 0:
        raise TorrentError("the torrent content is empty")
    piece_length = 1 << piece_exponent(total)
    pieces = bytearray()
    current = hashlib.sha1(usedforsecurity=False)
    filled = 0
    done = 0
    for path, _parts in files:
        with path.open("rb") as handle:
            while chunk := handle.read(READ_BYTES):
                view = memoryview(chunk)
                while view:
                    take = min(len(view), piece_length - filled)
                    current.update(view[:take])
                    filled += take
                    view = view[take:]
                    if filled == piece_length:
                        pieces += current.digest()
                        current = hashlib.sha1(usedforsecurity=False)
                        filled = 0
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    if filled:
        pieces += current.digest()
    if done != total:
        raise TorrentError("the torrent content changed while it was hashed")
    info: dict[str, Any] = {
        "name": content.name,
        "piece length": piece_length,
        "pieces": bytes(pieces),
        "private": 1,
        "source": source,
    }
    if content.is_file():
        info["length"] = total
    else:
        info["files"] = [
            {"length": path.stat().st_size, "path": list(parts)} for path, parts in files
        ]
    data = bencode(
        {
            "announce": announce,
            "created by": f"Accofil BDEncode {__version__}",
            "info": info,
        }
    )
    return BuiltTorrent(
        data=data,
        info_hash=info_hash(data),
        piece_length=piece_length,
        piece_count=len(pieces) // 20,
        total_bytes=total,
    )
