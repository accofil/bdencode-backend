"""Release names that are safe as a folder and file name on every platform."""

from __future__ import annotations

import unicodedata

_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_SAFE_RELEASE_PUNCTUATION = frozenset("._ ()'&+-")


class ReleaseNameError(ValueError):
    pass


def validate_release_name(release_name: str) -> str:
    """Return a safe canonical release root or raise ``ReleaseNameError``."""

    if not isinstance(release_name, str):
        raise ReleaseNameError("release_name must be a string")
    if unicodedata.normalize("NFC", release_name) != release_name:
        raise ReleaseNameError("release_name must use canonical NFC text")
    if not release_name or len(release_name) > 240:
        raise ReleaseNameError("release_name must contain 1-240 characters")
    if not unicodedata.category(release_name[0]).startswith(("L", "N")):
        raise ReleaseNameError("release_name must start with a letter or number")
    if any(
        not unicodedata.category(character).startswith(("L", "N"))
        and character not in _SAFE_RELEASE_PUNCTUATION
        for character in release_name
    ):
        raise ReleaseNameError(
            "release_name contains a path-unsafe or ambiguous Unicode character"
        )
    if release_name[-1] in {".", " "}:
        raise ReleaseNameError("release_name cannot end in a dot or space")
    if release_name.casefold().endswith(".mkv"):
        raise ReleaseNameError("release_name must not include the .mkv suffix")
    first_component = release_name.split(".", 1)[0].casefold()
    if first_component in {item.casefold() for item in _WINDOWS_RESERVED_NAMES}:
        raise ReleaseNameError("release_name uses a reserved filesystem name")
    if len(f"{release_name}.mkv".encode("utf-8")) > 255:
        raise ReleaseNameError("release payload filename exceeds 255 bytes")
    return release_name


def payload_path_for(release_name: str) -> str:
    """The public payload path of a release: ``Name/Name.mkv``."""

    safe_name = validate_release_name(release_name)
    return f"{safe_name}/{safe_name}.mkv"


__all__ = ["ReleaseNameError", "payload_path_for", "validate_release_name"]
