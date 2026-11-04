"""The tracker and qBittorrent clients against fake servers; no real service is touched."""

from __future__ import annotations

import json
from typing import Callable

import httpx
import pytest

from bdencode.qbittorrent import CATEGORY, QbittorrentClient, QbittorrentError, validate_url
from bdencode.torrent_file import bencode
from bdencode.trackers import SessionExpired, TrackerError, aither, ncore

SECRET = "s3cr3t-token-that-must-stay-private"
TORRENT = bencode({"announce": "x", "info": {"name": "M.mkv", "length": 1, "piece length": 16384, "pieces": b"\0" * 20}})


def _http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _aither(handler: Callable[[httpx.Request], httpx.Response]) -> aither.AitherClient:
    return aither.AitherClient(SECRET, client=_http(handler))


def test_aither_names_have_spaces_except_inside_numbers() -> None:
    assert (
        aither.display_name("Housemaid.2025.2160p.UHD.BluRay.REMUX.DV.HDR.HEVC.TrueHD.7.1.Atmos-TEST")
        == "Housemaid 2025 2160p UHD BluRay REMUX DV HDR HEVC TrueHD 7.1 Atmos-TEST"
    )
    assert aither.display_name("A.Film.1987.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-X") == (
        "A Film 1987 1080p BluRay REMUX AVC DTS-HD MA 5.1-X"
    )


def test_aither_fields_of_a_uhd_remux_and_an_encode() -> None:
    remux = aither.upload_fields(
        name="n",
        description="d",
        mediainfo="m",
        category="Movie",
        remux=True,
        resolution="2160p",
        tmdb_id=42,
        imdb_id="tt0123456",
        dynamic_range=("DV", "HDR"),
        personal_release=True,
    )
    assert remux["category_id"] == "1"
    assert remux["type_id"] == "2"
    assert remux["resolution_id"] == "2"
    assert remux["tmdb"] == "42"
    assert remux["imdb"] == "0123456"
    assert remux["dv"] == "1"
    assert remux["hdr"] == "1"
    assert remux["sd"] == "0"
    assert remux["personal_release"] == "1"
    assert remux["anonymous"] == "0"
    assert remux["internal"] == "0"
    encode = aither.upload_fields(
        name="n",
        description="d",
        mediainfo="m",
        category="Movie",
        remux=False,
        resolution="1080p",
        tmdb_id=42,
        imdb_id=None,
    )
    assert encode["type_id"] == "3"
    assert encode["resolution_id"] == "3"
    assert encode["imdb"] == "0"
    assert "dv" not in encode and "hdr" not in encode
    with pytest.raises(TrackerError):
        aither.upload_fields(
            name="n", description="d", mediainfo="m", category="Movie", remux=False,
            resolution="1440p", tmdb_id=1, imdb_id=None,
        )


def test_aither_uses_the_bearer_header_and_marks_the_exact_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        assert SECRET not in str(request.url)
        assert request.url.path == "/api/torrents/filter"
        assert request.url.params["tmdbId"] == "42"
        assert request.url.params["resolutions[]"] == "3"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"attributes": {"name": "Film 2020 1080p BluRay REMUX AVC DD 5.1-X", "size": 10, "details_link": "https://aither.cc/torrents/1", "download_link": "https://aither.cc/torrent/download/1.private", "trumpable": True}},
                    {"attributes": {"name": "Film 2020 1080p BluRay x264 DD 5.1-Y"}},
                ]
            },
        )

    matches = _aither(handler).search(
        tmdb_id=42, category="Movie", resolution="1080p", release_name="Film.2020.1080p.BluRay.REMUX.AVC.DD.5.1-X"
    )

    assert [item.exact for item in matches] == [True, False]
    assert matches[0].trumpable and matches[0].size == 10
    assert "private" not in matches[0].url


def test_aither_banned_groups_follow_the_cursor() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if "cursor" not in request.url.params:
            return httpx.Response(200, json={"data": [{"name": "BaD"}], "meta": {"next_cursor": "c2"}})
        return httpx.Response(200, json={"data": [{"attributes": {"name": "Other"}}], "meta": {}})

    assert _aither(handler).banned_groups() == {"bad", "other"}
    assert calls[1]["cursor"] == "c2"


def test_aither_refused_key_is_an_expired_login() -> None:
    client = _aither(lambda _request: httpx.Response(401, json={}))

    with pytest.raises(SessionExpired):
        client.check_connection()


def test_aither_upload_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/torrents/upload"
        body = request.content
        assert b'name="torrent"; filename="torrent.torrent"' in body
        assert b'name="name"' in body
        return httpx.Response(
            200, json={"success": True, "data": "https://aither.cc/torrent/download/777.privatekey", "message": "ok"}
        )

    result, link = _aither(handler).upload({"name": "Film"}, TORRENT)

    assert result.accepted and result.torrent_id == 777
    assert result.url == "https://aither.cc/torrents/777"
    assert "privatekey" not in result.url
    assert link.endswith("privatekey")


def test_aither_upload_refused_with_reasons() -> None:
    client = _aither(
        lambda _request: httpx.Response(
            404, json={"success": False, "message": "Validation Error.", "data": {"name": ["taken"]}}
        )
    )

    result, link = client.upload({"name": "Film"}, TORRENT)

    assert result.rejected and not result.accepted and not link
    assert "name: taken" in result.errors


@pytest.mark.parametrize(
    "response",
    [httpx.Response(500, text="<html>oops</html>"), httpx.Response(502, json={"message": "bad gateway"})],
)
def test_aither_unclear_answers_are_neither_accepted_nor_refused(response: httpx.Response) -> None:
    result, _link = _aither(lambda _request: response).upload({"name": "Film"}, TORRENT)

    assert not result.accepted and not result.rejected and result.errors


def test_a_broken_connection_during_the_upload_is_unclear_and_sent_once() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    result, _link = _aither(handler).upload({"name": "Film"}, TORRENT)

    assert len(calls) == 1
    assert not result.accepted and not result.rejected


def test_aither_download_refuses_a_foreign_link_and_a_non_torrent() -> None:
    client = _aither(lambda _request: httpx.Response(200, content=b"<html>"))

    with pytest.raises(TrackerError):
        client.download_torrent("https://elsewhere.example/x")
    with pytest.raises(TrackerError):
        client.download_torrent("https://aither.cc/torrent/download/1.key")


COOKIES_TXT = (
    "# Netscape HTTP Cookie File\n"
    ".ncore.pro\tTRUE\t/\tTRUE\t0\tnick\tvalue1\n"
    "#HttpOnly_.ncore.pro\tTRUE\t/\tTRUE\t0\tpass\tvalue2\n"
    ".other.example\tTRUE\t/\tTRUE\t0\tforeign\tvalue3\n"
)
UPLOAD_PAGE = (
    '<form id="feltoltes" method="post"><input type="hidden" name="getUnique" value="abcdef0123456789abcd">'
    '<input type="hidden" name="MAX_FILE_SIZE" value="1000"><input type="text" name="torrent_nev"></form>'
)


def test_cookie_export_keeps_only_ncore() -> None:
    assert ncore.parse_cookie_export(COOKIES_TXT) == "nick=value1; pass=value2"
    assert ncore.parse_cookie_export("nick=a; pass=b") == "nick=a; pass=b"
    with pytest.raises(ValueError):
        ncore.parse_cookie_export("nothing useful")


def test_ncore_category_and_track_lines() -> None:
    assert ncore.category_for(["hun", "eng"]) == "hd_hun"
    assert ncore.category_for(["eng", "hun"]) == "hd"
    assert ncore.audio_line(
        [{"language": "hun", "channels": 6}, {"language": "eng", "channels": 2, "title": "Commentary"}]
    ) == "magyar 5.1, angol 2.0 kommentár"
    assert ncore.subtitle_line(
        [{"language": "hun"}, {"language": "hun"}, {"language": "eng", "forced": True}]
    ) == "magyar, angol kiegészítő"


def test_ncore_form_keeps_rendered_details_out_of_the_description() -> None:
    film = ncore.FilmForm(
        name="Film 1080p REMUX",
        category="hd",
        description="Hangsáv: angol 5.1\n[b]Felirat[/b]: magyar\nEgy hosszú és részletes történet.\n\nForrás: Blu-ray\n",
        imdb_id="tt0123456",
        year="2020",
        title_hu="Film",
        title_en="Film",
        country="United States, England",
        menu=False,
    )

    fields = ncore.form_fields("t" * 20, film)

    assert fields["eredeti"] == "nem"
    assert fields["tipus"] == "hd"
    assert fields["orszag"] == "USA, UK"
    assert fields["menu"] == "nincs"
    assert "Hangsáv" not in fields["szoveg"] and "Felirat" not in fields["szoveg"]
    assert "Forrás: Blu-ray" in fields["szoveg"]
    assert ncore.form_problems(fields, {}) == [
        f"the file part {part} is missing" for part in ("torrent_fajl", "techinfo_fajl", "kep1", "kep2", "kep3")
    ]


def test_ncore_form_problems_cover_what_the_page_refuses() -> None:
    film = ncore.FilmForm(
        name="Film", category="xvid", description="rövid", imdb_id="123", year="2020", title_hu="", title_en=""
    )

    problems = ncore.form_problems(ncore.form_fields("t" * 20, film), {})

    assert any("30 characters" in item for item in problems)
    assert any("Forrás" in item for item in problems)
    assert any("6 characters" in item for item in problems)
    assert any("hd and hd_hun" in item for item in problems)
    assert any("tt1234567" in item for item in problems)
    assert any("title" in item for item in problems)


def _ncore(handler: Callable[[httpx.Request], httpx.Response]) -> ncore.NcoreClient:
    client = ncore.NcoreClient("nick=a; pass=b", client=_http(handler), sleep=lambda _seconds: None)
    client.find_attempts = 2
    return client


def test_ncore_token_hidden_fields_and_expired_login() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["cookie"] == "nick=a; pass=b"
        return httpx.Response(200, text=UPLOAD_PAGE, headers={"content-type": "text/html"})

    client = _ncore(handler)
    assert client.upload_token() == "abcdef0123456789abcd"
    assert client._hidden["MAX_FILE_SIZE"] == "1000"

    expired = _ncore(
        lambda _request: httpx.Response(200, text='<input name="pass">', headers={"content-type": "text/html"})
    )
    with pytest.raises(SessionExpired):
        expired.check_connection()


def test_ncore_search_merges_hits_and_marks_the_exact_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["kivalasztott_tipus"] == "hd_hun,hd"
        hits = (
            [{"torrent_id": "5", "release_name": "Film.2020-X", "size": "9"}]
            if request.url.params["miben"] == "name"
            else [
                {"torrent_id": "5", "release_name": "Film.2020-X", "size": "9"},
                {"torrent_id": "6", "release_name": "Film 2020 1080p"},
            ]
        )
        return httpx.Response(
            200,
            content=json.dumps({"results": hits, "total_results": str(len(hits)), "perpage": "50"}),
            headers={"content-type": "application/json"},
        )

    matches = _ncore(handler).search(imdb_id="tt1", release_name="Film.2020-X")

    assert [(item.name, item.exact) for item in matches] == [("Film.2020-X", True), ("Film 2020 1080p", False)]
    assert matches[0].url.endswith("id=5")


def test_ncore_search_treats_no_hits_as_empty_and_other_html_as_an_error() -> None:
    empty = _ncore(lambda _r: httpx.Response(200, text="Nincs találat!", headers={"content-type": "text/html"}))
    assert empty.search(imdb_id=None, release_name="Film") == ()
    changed = _ncore(lambda _r: httpx.Response(200, text="<p>?</p>", headers={"content-type": "text/html"}))
    with pytest.raises(TrackerError):
        changed.search(imdb_id=None, release_name="Film")


def _no_hits(request: httpx.Request) -> httpx.Response | None:
    if request.url.path == "/torrents.php" and request.url.params.get("jsons"):
        return httpx.Response(200, text="Nincs találat", headers={"content-type": "text/html"})
    return None


def test_ncore_upload_found_from_the_redirect_and_with_crlf_text() -> None:
    posted: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if (found := _no_hits(request)) is not None:
            return found
        if request.url.path == "/upload.php":
            posted.append(request.content)
            return httpx.Response(302, headers={"location": "/torrents.php?action=details&id=99"})
        return httpx.Response(200, text="ok", headers={"content-type": "text/html"})

    result = _ncore(handler).upload(
        {"torrent_nev": "Film", "szoveg": "a\nb"}, {"torrent_fajl": ("f.torrent", TORRENT, "application/x-bittorrent")}
    )

    assert result.accepted and result.torrent_id == 99
    assert b"a\r\nb" in posted[0]
    assert len(posted) == 1


def test_ncore_upload_error_box_is_a_refusal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if (found := _no_hits(request)) is not None:
            return found
        return httpx.Response(
            200,
            text='<div class="fobox_fej">Hiba!</div><ul><li>Rossz kategória</li></ul></table>',
            headers={"content-type": "text/html"},
        )

    result = _ncore(handler).upload(
        {"torrent_nev": "Film"}, {"torrent_fajl": ("f.torrent", TORRENT, "application/x-bittorrent")}
    )

    assert result.rejected and result.errors == ("Rossz kategória",)


def test_ncore_unclear_answer_is_looked_up_and_never_sent_again() -> None:
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if (found := _no_hits(request)) is not None:
            return found
        posts.append(request)
        return httpx.Response(200, text="<p>valami</p>", headers={"content-type": "text/html"})

    result = _ncore(handler).upload(
        {"torrent_nev": "Film"}, {"torrent_fajl": ("f.torrent", TORRENT, "application/x-bittorrent")}
    )

    assert len(posts) == 1
    assert not result.accepted and not result.rejected
    assert "no new torrent" in result.errors[0]


def test_ncore_unclear_answer_with_a_new_identical_torrent_counts_as_accepted() -> None:
    seen = {"searches": 0}
    passkey = "a" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/upload.php":
            return httpx.Response(200, text="<p>?</p>", headers={"content-type": "text/html"})
        if request.url.params.get("jsons"):
            seen["searches"] += 1
            hits = [] if seen["searches"] == 1 else [{"torrent_id": "7", "release_name": "Film"}]
            return httpx.Response(
                200,
                content=json.dumps({"results": hits, "total_results": str(len(hits)), "perpage": "50"}),
                headers={"content-type": "application/json"},
            )
        if request.url.params.get("action") == "details":
            return httpx.Response(
                200, text=f"action=download&id=7&key={passkey}", headers={"content-type": "text/html"}
            )
        assert request.url.params["key"] == passkey
        return httpx.Response(200, content=TORRENT, headers={"content-type": "application/x-bittorrent"})

    result = _ncore(handler).upload(
        {"torrent_nev": "Film"}, {"torrent_fajl": ("f.torrent", TORRENT, "application/x-bittorrent")}
    )

    assert result.accepted and result.torrent_id == 7
    assert result.note


def test_qbittorrent_address_rules() -> None:
    assert validate_url("http://127.0.0.1:8080/") == "http://127.0.0.1:8080"
    for bad in ("ftp://x", "http://user:pass@x", "http://x/api", "127.0.0.1:8080", "http://x?a=1"):
        with pytest.raises(ValueError):
            validate_url(bad)


class _FakeQbit:
    def __init__(self, states: list[tuple[str, float]]) -> None:
        self.states = states
        self.added: list[bytes] = []
        self.forced = False
        self.needs_login = True
        self.logged_in = False
        self.present = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v2/")
        assert request.headers["referer"] == "http://qb:8080"
        if path == "auth/login":
            assert b"password=pw" in request.content
            self.logged_in = True
            return httpx.Response(200, text="Ok.")
        if self.needs_login and not self.logged_in:
            return httpx.Response(403, text="Forbidden")
        if path == "app/version":
            return httpx.Response(200, text="v5.0.0")
        if path == "torrents/createCategory":
            assert request.content == f"category={CATEGORY}".encode()
            return httpx.Response(409)
        if path == "torrents/add":
            self.added.append(request.content)
            self.present = True
            return httpx.Response(200, text="Ok.")
        if path == "torrents/setForceStart":
            self.forced = True
            return httpx.Response(200)
        if path == "torrents/info":
            if not self.present:
                return httpx.Response(200, json=[])
            state, progress = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return httpx.Response(200, json=[{"state": state, "progress": progress}])
        return httpx.Response(404)


def _qbit(fake: _FakeQbit) -> QbittorrentClient:
    clock = iter(range(0, 100000, 10))
    return QbittorrentClient(
        "http://qb:8080",
        username="user",
        password="pw",
        client=httpx.Client(transport=httpx.MockTransport(fake)),
        sleep=lambda _seconds: None,
        monotonic=lambda: float(next(clock)),
    )


def test_qbittorrent_adds_into_its_own_category_and_waits_for_the_check() -> None:
    fake = _FakeQbit([("checkingUP", 0.5), ("stalledUP", 1.0)])
    client = _qbit(fake)

    client.add(TORRENT, info_hash="a" * 40, save_path="/data/seeding/1")
    result = client.wait_until_seeding("a" * 40)

    assert result.state == "stalledUP"
    body = fake.added[0]
    assert CATEGORY.encode() in body
    assert b"/data/seeding/1" in body
    assert b'name="skip_checking"\r\n\r\nfalse' in body
    assert b'name="autoTMM"\r\n\r\nfalse' in body
    assert b'name="contentLayout"\r\n\r\nOriginal' in body


def test_qbittorrent_does_not_add_the_same_torrent_twice() -> None:
    fake = _FakeQbit([("stalledUP", 1.0)])
    fake.present = True

    _qbit(fake).add(TORRENT, info_hash="a" * 40, save_path="/x")

    assert fake.added == []


def test_qbittorrent_force_starts_a_queued_release() -> None:
    fake = _FakeQbit([("queuedUP", 1.0), ("forcedUP", 1.0)])
    fake.present = True

    result = _qbit(fake).wait_until_seeding("a" * 40)

    assert fake.forced
    assert result.state == "forcedUP"


@pytest.mark.parametrize(
    ("state", "text"),
    [(("missingFiles", 0.0), "missingFiles"), (("error", 0.0), "error"), (("stalledDL", 0.4), "40.0%")],
)
def test_qbittorrent_missing_data_is_an_error_not_a_download(state: tuple[str, float], text: str) -> None:
    fake = _FakeQbit([state])
    fake.present = True

    with pytest.raises(QbittorrentError, match=text):
        _qbit(fake).wait_until_seeding("a" * 40)


def test_qbittorrent_gives_up_at_the_deadline() -> None:
    fake = _FakeQbit([("checkingUP", 0.1)])
    fake.present = True

    with pytest.raises(QbittorrentError, match="in time"):
        _qbit(fake).wait_until_seeding("a" * 40, wait_seconds=30)


def test_qbittorrent_wrong_password_is_reported_without_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("auth/login"):
            return httpx.Response(200, text="Fails.")
        return httpx.Response(403)

    client = QbittorrentClient(
        "http://qb:8080", username="user", password="hunter2", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(QbittorrentError) as caught:
        client.check_connection()
    assert "hunter2" not in str(caught.value)
