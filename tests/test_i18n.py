"""The interface language reaches every API answer, sync handlers included."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from bdencode.api import create_app
from bdencode.db import Database
from bdencode.i18n import (
    bilingual,
    current_language,
    parse_accept_language,
    pick,
    t,
    use_language,
)


def test_accept_language_parsing() -> None:
    assert parse_accept_language(None) == "hu"
    assert parse_accept_language("") == "hu"
    assert parse_accept_language("hu") == "hu"
    assert parse_accept_language("hu-HU,hu;q=0.9,en;q=0.8") == "hu"
    assert parse_accept_language("en") == "en"
    assert parse_accept_language("en-GB,en;q=0.9") == "en"
    assert parse_accept_language("de-DE") == "en"
    assert parse_accept_language("*") == "hu"


def test_texts_follow_the_current_language() -> None:
    assert t("igen", "yes") == "igen"
    with use_language("en"):
        assert t("igen", "yes") == "yes"
        assert pick(bilingual("igen", "yes")) == "yes"
        assert pick("régi szöveg") == "régi szöveg"
    assert pick(bilingual("igen", "yes")) == "igen"
    assert pick({"hu": "csak magyar"}, "en") == "csak magyar"


def test_the_header_sets_the_language_for_sync_and_async_handlers(tmp_path) -> None:
    app = create_app(Database(tmp_path / "i18n.sqlite3"))

    @app.get("/api/v1/test-language-sync")
    def sync_language() -> dict[str, str]:
        return {"language": current_language(), "text": t("Mentés", "Save")}

    @app.get("/api/v1/test-language-async")
    async def async_language() -> dict[str, str]:
        await asyncio.sleep(0)
        return {"language": current_language()}

    with TestClient(app) as client:
        assert client.get("/api/v1/test-language-sync").json() == {"language": "hu", "text": "Mentés"}
        english = client.get("/api/v1/test-language-sync", headers={"Accept-Language": "en"}).json()
        assert english == {"language": "en", "text": "Save"}
        assert client.get("/api/v1/test-language-async", headers={"Accept-Language": "en-US"}).json() == {"language": "en"}
        # The language never leaks into the next request.
        assert client.get("/api/v1/test-language-sync").json()["language"] == "hu"
