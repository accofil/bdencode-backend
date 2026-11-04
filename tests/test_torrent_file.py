from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from bdencode.torrent_file import (
    MAX_PIECE_EXPONENT,
    MIN_PIECE_EXPONENT,
    TorrentError,
    bdecode,
    bencode,
    build_torrent,
    file_names,
    info_hash,
    piece_exponent,
    same_content,
)


def test_bencode_round_trip_sorts_the_keys() -> None:
    encoded = bencode({"b": 1, "a": [b"x", "ü"]})

    assert encoded == "d1:al1:x2:üe1:bi1ee".encode("utf-8")
    assert bdecode(encoded) == {b"a": [b"x", "ü".encode("utf-8")], b"b": 1}


@pytest.mark.parametrize("broken", [b"", b"x", b"i1", b"5:ab", b"d1:ai1e", b"i1ei2e", b"d i1ei2ee"])
def test_broken_bencode_is_refused(broken: bytes) -> None:
    with pytest.raises(TorrentError):
        bdecode(broken)


def test_the_piece_size_keeps_the_torrent_small() -> None:
    assert piece_exponent(1) == MIN_PIECE_EXPONENT
    assert 1 << piece_exponent(80 * 1024**3) == 32 * 1024**2
    assert piece_exponent(10 * 1024**5) == MAX_PIECE_EXPONENT


def test_a_single_file_torrent_is_private_and_hashes_every_piece(tmp_path: Path) -> None:
    content = tmp_path / "Movie.mkv"
    piece = 1 << MIN_PIECE_EXPONENT
    data = bytes(range(256)) * (piece // 256) + b"tail"
    content.write_bytes(data)
    seen: list[tuple[int, int]] = []

    built = build_torrent(
        content, source="Aither", announce="https://aither.cc/announce", progress=lambda *item: seen.append(item)
    )

    document = bdecode(built.data)
    info = document[b"info"]
    assert document[b"announce"] == b"https://aither.cc/announce"
    assert info[b"private"] == 1
    assert info[b"source"] == b"Aither"
    assert info[b"name"] == b"Movie.mkv"
    assert info[b"length"] == len(data)
    assert b"files" not in info
    assert info[b"piece length"] == piece
    assert info[b"pieces"] == hashlib.sha1(data[:piece]).digest() + hashlib.sha1(data[piece:]).digest()
    assert built.info_hash == hashlib.sha1(bencode(info)).hexdigest()
    assert info_hash(built.data) == built.info_hash
    assert seen[-1] == (len(data), len(data))
    assert file_names(built.data) == ("Movie.mkv",)


def test_a_folder_torrent_runs_its_pieces_across_the_files(tmp_path: Path) -> None:
    folder = tmp_path / "Movie"
    folder.mkdir()
    first = b"a" * 300_000
    second = b"b" * 100_000
    (folder / "Movie.mkv").write_bytes(first)
    (folder / "sample.mkv").write_bytes(second)

    built = build_torrent(folder, source="nCore", announce="https://ncore.pro/announce")

    info = bdecode(built.data)[b"info"]
    piece = info[b"piece length"]
    joined = first + second
    assert info[b"pieces"] == hashlib.sha1(joined[:piece]).digest() + hashlib.sha1(joined[piece:]).digest()
    assert [item[b"path"] for item in info[b"files"]] == [[b"Movie.mkv"], [b"sample.mkv"]]
    assert file_names(built.data) == ("Movie/Movie.mkv", "Movie/sample.mkv")


def test_same_content_ignores_what_a_tracker_rewrites(tmp_path: Path) -> None:
    content = tmp_path / "Movie.mkv"
    content.write_bytes(b"x" * 1000)
    ours = build_torrent(content, source="Aither", announce="https://aither.cc/announce")
    document = bdecode(ours.data)
    document[b"announce"] = b"https://aither.cc/announce/secret"
    document[b"info"][b"source"] = b"[aither.cc] Aither"
    theirs = bencode(document)

    assert info_hash(theirs) != ours.info_hash
    assert same_content(ours.data, theirs)

    document[b"info"][b"pieces"] = b"\0" * 20
    assert not same_content(ours.data, bencode(document))
    assert not same_content(ours.data, b"not a torrent")


def test_an_empty_or_linked_content_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "Empty"
    folder.mkdir()
    with pytest.raises(TorrentError):
        build_torrent(folder, source="x", announce="y")
    empty = tmp_path / "empty.mkv"
    empty.write_bytes(b"")
    with pytest.raises(TorrentError):
        build_torrent(empty, source="x", announce="y")
