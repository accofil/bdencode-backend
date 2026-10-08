"""Release names that are safe as folder and file names (kept from the torrent era)."""

from __future__ import annotations

import pytest

from bdencode.release.names import ReleaseNameError, payload_path_for


@pytest.mark.parametrize(
    "release_name",
    [
        "../escape",
        "Folder/Release",
        "Folder\\Release",
        "Café.2024",
        "Release.mkv",
        "CON.Title.2024",
        "Trailing.",
        "Unsafe:Name",
        "emoji.\U0001f4bf",
    ],
)
def test_release_payload_path_rejects_traversal_unicode_and_aliases(
    release_name: str,
) -> None:
    with pytest.raises(ReleaseNameError):
        payload_path_for(release_name)


def test_release_payload_path_accepts_canonical_unicode_letters() -> None:
    name = "Árvíztűrő.Tükörfúrógép.2024"

    assert payload_path_for(name) == f"{name}/{name}.mkv"
