"""The interface language of the current API request.

The web interface sends ``Accept-Language: hu`` or ``en``; the API sets it for
the request and every message built while answering uses ``t(hu, en)``.
Without a request (worker, CLI) and without the header the language is
Hungarian, as before 3.6.  Texts that the worker stores for later display
(live step labels) are stored in both languages and picked when read.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Literal

Language = Literal["hu", "en"]
DEFAULT_LANGUAGE: Language = "hu"

_language: ContextVar[Language] = ContextVar("bdencode_language", default=DEFAULT_LANGUAGE)


def parse_accept_language(value: str | None) -> Language:
    """Hungarian for a Hungarian first choice or no header, else English."""

    if not value or not value.strip():
        return DEFAULT_LANGUAGE
    first = value.split(",", 1)[0].split(";", 1)[0].strip().lower()
    if first.startswith("hu"):
        return "hu"
    if first in {"*", ""}:
        return DEFAULT_LANGUAGE
    return "en"


def current_language() -> Language:
    return _language.get()


def set_language(language: Language) -> Token[Language]:
    return _language.set(language)


def reset_language(token: Token[Language]) -> None:
    _language.reset(token)


@contextmanager
def use_language(language: Language) -> Iterator[None]:
    token = _language.set(language)
    try:
        yield
    finally:
        _language.reset(token)


def t(hu: str, en: str) -> str:
    """The text in the current language."""

    return hu if _language.get() == "hu" else en


def bilingual(hu: str, en: str) -> dict[str, str]:
    """Both texts, for a value stored now and shown later."""

    return {"hu": hu, "en": en}


def pick(value: Any, language: Language | None = None) -> Any:
    """A stored bilingual text in ``language`` (default: the current one).

    Plain strings (texts stored before 3.6) are returned unchanged.
    """

    if isinstance(value, Mapping) and isinstance(value.get("hu"), str):
        chosen = language or _language.get()
        text = value.get(chosen)
        return text if isinstance(text, str) else value["hu"]
    return value
