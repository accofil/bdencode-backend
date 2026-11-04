"""nCore's upload page, adapted from AccoFIL NCUpload (MIT licence, the same author).

nCore has no upload API: this is the form a browser would post, with the login
cookies the operator exported.  Only own films are handled here: categories
``hd`` and ``hd_hun``, techinfo instead of an NFO, three pictures and, over
2 GiB, a sample next to the MKV.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
import re
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from . import SessionExpired, TrackerError, TrackerMatch, UploadResult, USER_AGENT
from ..torrent_file import TorrentError, info_hash, same_content

BASE_URL = "https://ncore.pro"
ANNOUNCE = "https://ncore.pro/announce"
SOURCE_TAG = "nCore"
CREDENTIAL = "tracker-ncore-cookies"
CATEGORY_HUNGARIAN = "hd_hun"
CATEGORY_FOREIGN = "hd"
SAMPLE_OVER_BYTES = 2 * 1024**3
UHD_SAMPLE_MIN_BYTES = 200 * 1024**2
SAMPLE_MIN_SECONDS = 60
MAX_PICTURE_BYTES = 5 * 1024**2
MIN_DESCRIPTION_CHARS = 30
REQUEST_TIMEOUT = 60.0
UPLOAD_TIMEOUT = 300.0
_COOKIE_NAME = re.compile(r"[A-Za-z0-9_.\-]+")
_INPUT_TAG = re.compile(r"<input\b[^>]*>", re.I | re.S)
_ATTRIBUTE = re.compile(r"""([a-zA-Z_:][-\w:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?""")
_UPLOAD_FORM = re.compile(r"""<form\b[^>]*\bid=["']feltoltes["'][^>]*>(.*?)</form>""", re.I | re.S)
_ERROR_BOX = re.compile(r'fobox_fej"[^>]*>\s*Hiba!?\s*</div>(.*?)(?:</table>|class="fobox_fej"|$)', re.S)
_LIST_ITEM = re.compile(r"<li>(.*?)</li>", re.S)
_PASSKEY = re.compile(r"action=download&(?:amp;)?id=\d+&(?:amp;)?key=([0-9a-fA-F]{32})")
_MOVIE_INPUT = re.compile(r'<input[^>]*id="(movie_[a-z_]+)"[^>]*value="([^"]*)"', re.S)
_META_REFRESH = re.compile(
    r"""<meta\b[^>]*http-equiv=["']?refresh["']?[^>]*content=["']?\s*\d+\s*;\s*url=([^"'>\s]+)""", re.I
)
_COUNTRY_NAMES = {
    "United States": "USA",
    "United States of America": "USA",
    "United Kingdom": "UK",
    "England": "UK",
}
_LANGUAGES = {
    "hu": "magyar", "hun": "magyar", "en": "angol", "eng": "angol", "de": "német", "ger": "német",
    "deu": "német", "fr": "francia", "fre": "francia", "fra": "francia", "it": "olasz", "ita": "olasz",
    "es": "spanyol", "spa": "spanyol", "pt": "portugál", "por": "portugál", "ru": "orosz", "rus": "orosz",
    "pl": "lengyel", "pol": "lengyel", "cs": "cseh", "cze": "cseh", "ces": "cseh", "sk": "szlovák",
    "slo": "szlovák", "slk": "szlovák", "ro": "román", "rum": "román", "ron": "román", "hr": "horvát",
    "hrv": "horvát", "sr": "szerb", "srp": "szerb", "sl": "szlovén", "slv": "szlovén", "bg": "bolgár",
    "bul": "bolgár", "uk": "ukrán", "ukr": "ukrán", "nl": "holland", "dut": "holland", "nld": "holland",
    "ja": "japán", "jpn": "japán", "ko": "koreai", "kor": "koreai", "zh": "kínai", "chi": "kínai", "zho": "kínai",
}
_CHANNELS = {1: "1.0", 2: "2.0", 3: "2.1", 6: "5.1", 7: "6.1", 8: "7.1"}


def parse_cookie_export(text: str) -> str:
    """A browser's cookies.txt, or a ``name=value; name=value`` line, as one Cookie header.

    Only ncore.pro cookies are kept.  The value goes to the credential store, so
    it must be one line; nothing here may ever print it.
    """

    pairs: dict[str, str] = {}
    lines = text.splitlines()
    if any(line.count("\t") >= 6 for line in lines):
        for line in lines:
            parts = line.removeprefix("#HttpOnly_").split("\t")
            if len(parts) < 7 or parts[0].startswith("#"):
                continue
            domain, name, value = parts[0], parts[5], parts[6].strip()
            if domain.lstrip(".").casefold().endswith("ncore.pro"):
                pairs[name] = value
    else:
        for item in " ".join(lines).split(";"):
            name, separator, value = item.strip().partition("=")
            if separator:
                pairs[name.strip()] = value.strip()
    pairs = {name: value for name, value in pairs.items() if _COOKIE_NAME.fullmatch(name) and value}
    if not pairs:
        raise ValueError("no nCore cookie was found in the text")
    header = "; ".join(f"{name}={value}" for name, value in pairs.items())
    if len(header) > 3000 or any(not " " <= char <= "~" for char in header):
        raise ValueError("the nCore cookies have an unexpected form")
    return header


def category_for(languages: Sequence[str]) -> str:
    """The Hungarian category needs Hungarian audio in first place."""

    first = languages[0].casefold() if languages else ""
    return CATEGORY_HUNGARIAN if first in {"hu", "hun"} else CATEGORY_FOREIGN


def language_name(code: str) -> str:
    code = (code or "").casefold()
    if code in {"", "und"}:
        return "ismeretlen"
    return _LANGUAGES.get(code, _LANGUAGES.get(code[:2], code))


def audio_line(tracks: Sequence[Mapping[str, Any]]) -> str:
    items: list[str] = []
    for track in tracks:
        channels = track.get("channels")
        label = _CHANNELS.get(channels, str(channels)) if isinstance(channels, int) and channels else ""
        text = f"{language_name(str(track.get('language') or ''))} {label}".strip()
        title = str(track.get("title") or "").casefold()
        if "comment" in title or "kommentár" in title:
            text += " kommentár"
        items.append(text)
    return ", ".join(items) or "nincs"


def subtitle_line(tracks: Sequence[Mapping[str, Any]]) -> str:
    items: list[str] = []
    for track in tracks:
        text = language_name(str(track.get("language") or ""))
        title = str(track.get("title") or "").casefold()
        if track.get("forced") or "forced" in title or "kiegészítő" in title:
            text += " kiegészítő"
        items.append(text)
    return ", ".join(dict.fromkeys(items)) or "nincs"


def clean_description(text: str) -> str:
    """nCore prepends menu, subtitles, audio and extras from the form: never twice."""

    kept = [
        line
        for line in text.splitlines()
        if not re.match(
            r"(?i)^(?:Menü|Felirat\(ok\)|Felirat|Hangsáv|Extra)\s*:",
            re.sub(r"\[/?b\]", "", line, flags=re.I).strip(),
        )
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip() + "\n"


def description_problems(text: str) -> list[str]:
    problems: list[str] = []
    if len(text.strip()) < MIN_DESCRIPTION_CHARS:
        problems.append(f"the description needs at least {MIN_DESCRIPTION_CHARS} characters")
    source = re.search(r"(?im)^\s*forr[aá]s\s*:\s*(.+)", text)
    if not source or source.group(1).strip().casefold() == "ismeretlen":
        problems.append("the description must end with a known source: Forrás: ...")
    return problems


@dataclass(frozen=True)
class FilmForm:
    """What the upload form asks about one film; ``imdb_id`` is ``tt`` and digits."""

    name: str
    category: str
    description: str
    imdb_id: str
    year: str
    title_hu: str
    title_en: str
    title_other: str = ""
    country: str = ""
    runtime: str = ""
    directors: str = ""
    cast: str = ""
    subtitles: str = "nincs"
    audio: str = "nincs"
    extras: str = "nincs"
    menu: bool = False


def form_fields(token: str, film: FilmForm) -> dict[str, str]:
    return {
        "getUnique": token,
        "tipus": film.category,
        "torrent_nev": film.name.strip(),
        "eredeti": "nem",
        "szoveg": clean_description(film.description),
        "keresre": "nem",
        "keres_kodja": "",
        "mindent_tud1": "szabalyzat",
        "mindent_tud3": "seedeles",
        "imdb_id": film.imdb_id.strip(),
        "film_adatbazis": "",
        "megjelent": film.year,
        "dvd_megjelent": "",
        "orszag": ", ".join(
            _COUNTRY_NAMES.get(part.strip(), part.strip())
            for part in film.country.split(",")
            if part.strip()
        ),
        "hossz": film.runtime,
        "film_magyar_cim": film.title_hu,
        "film_angol_cim": film.title_en,
        "film_idegen_cim": film.title_other,
        "rendezo": film.directors,
        "szereplok": film.cast,
        "film_felirat": film.subtitles,
        "film_hangsav": film.audio,
        "film_extra": film.extras,
        "menu": "van" if film.menu else "nincs",
    }


def form_problems(fields: Mapping[str, str], files: Mapping[str, object]) -> list[str]:
    """What the upload page itself would refuse."""

    problems = description_problems(fields.get("szoveg", ""))
    if len(fields.get("torrent_nev", "")) < 6:
        problems.append("the torrent name needs at least 6 characters")
    if fields.get("tipus") not in {CATEGORY_HUNGARIAN, CATEGORY_FOREIGN}:
        problems.append("only the film categories hd and hd_hun are supported")
    if not re.fullmatch(r"tt\d+", fields.get("imdb_id", "")):
        problems.append("the IMDb id must look like tt1234567")
    if not fields.get("film_magyar_cim") and not fields.get("film_angol_cim"):
        problems.append("a Hungarian or an English title is needed")
    for part in ("torrent_fajl", "techinfo_fajl", "kep1", "kep2", "kep3"):
        if part not in files:
            problems.append(f"the file part {part} is missing")
    return problems


def _plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_errors(body: str) -> list[str]:
    box = _ERROR_BOX.search(body)
    if not box:
        return []
    items = [item for item in (_plain(found) for found in _LIST_ITEM.findall(box.group(1))) if item]
    return items or [_plain(box.group(1))[:300] or "Hiba! (nCore gave no reason)"]


def _attributes(tag: str) -> dict[str, str]:
    return {
        found.group(1).lower(): html.unescape(next((group for group in found.groups()[1:] if group is not None), ""))
        for found in _ATTRIBUTE.finditer(tag[6:])
    }


def hidden_fields(page: str) -> dict[str, str]:
    """The upload form's hidden inputs, which a browser would post too."""

    form = _UPLOAD_FORM.search(page)
    fields: dict[str, str] = {}
    for tag in _INPUT_TAG.findall(form.group(1) if form else ""):
        attributes = _attributes(tag)
        if attributes.get("type", "").lower() == "hidden" and attributes.get("name") and "disabled" not in attributes:
            fields.setdefault(attributes["name"], attributes.get("value", ""))
    return fields


def parse_token(page: str) -> str | None:
    for tag in _INPUT_TAG.findall(page):
        attributes = _attributes(tag)
        if attributes.get("name") == "getUnique" and re.fullmatch(r"[0-9A-Za-z]{16,64}", attributes.get("value", "")):
            return attributes["value"]
    return None


def parse_imdb_movie(body: str) -> dict[str, str]:
    return {key: html.unescape(value) for key, value in _MOVIE_INPUT.findall(body)}


def details_id(url: str) -> int | None:
    parts = urlsplit(urljoin(f"{BASE_URL}/", html.unescape(url or "")))
    if not parts.path.endswith("/torrents.php"):
        return None
    query = parse_qs(parts.query)
    if query.get("action", [""])[0] != "details":
        return None
    value = query.get("id", [""])[0]
    return int(value) if value.isdigit() else None


def details_url(torrent_id: int) -> str:
    return f"{BASE_URL}/torrents.php?action=details&id={torrent_id}"


def _response_details_id(response: httpx.Response) -> int | None:
    candidates = [str(response.url)] + [item.headers.get("location", "") for item in reversed(response.history)]
    if "html" in response.headers.get("content-type", "html"):
        candidates += _META_REFRESH.findall(response.text)
    for url in candidates:
        found = details_id(url)
        if found:
            return found
    return None


def _is_login_page(response: httpx.Response) -> bool:
    if "login.php" in str(response.url):
        return True
    content_type = response.headers.get("content-type", "")
    if content_type and "html" not in content_type:
        return False
    text = response.text
    return 'name="pass"' in text and "getUnique" not in text


def _normal_name(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip().casefold()


def _to_int(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


class NcoreClient:
    def __init__(
        self,
        cookie_header: str,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cookie_header = cookie_header
        self._client = client or httpx.Client(follow_redirects=True)
        self._sleep = sleep
        self._hidden: dict[str, str] = {}
        self.find_attempts = 4
        self.find_delay = 5.0

    def close(self) -> None:
        self._client.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Cookie": self._cookie_header, "User-Agent": USER_AGENT}

    def _get(self, path: str, **params: Any) -> httpx.Response:
        try:
            response = self._client.get(
                urljoin(f"{BASE_URL}/", path),
                params=params or None,
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            # The exception text can hold the download link's passkey.
            raise TrackerError(f"nCore cannot be reached on {path} ({type(exc).__name__})") from None
        if _is_login_page(response):
            raise SessionExpired("the nCore cookies have expired: export them again from the browser")
        if response.status_code != 200:
            raise TrackerError(f"nCore answered HTTP {response.status_code} on {path}")
        return response

    def upload_token(self) -> str:
        page = self._get("upload.php").text
        token = parse_token(page)
        if not token:
            raise TrackerError("the upload page has no getUnique token")
        self._hidden = hidden_fields(page)
        return token

    def check_connection(self) -> str:
        self.upload_token()
        return "nCore login OK"

    def imdb_movie(self, imdb_id: str) -> dict[str, str]:
        digits = imdb_id.casefold().removeprefix("tt")
        return parse_imdb_movie(self._get("ajax.php", action="imdb_movie", imdb_movie=digits).text)

    def _search_raw(self, text: str, by: str, categories: Sequence[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        total = 0
        for page in range(1, 5):
            params: dict[str, str] = {
                "mire": text,
                "miben": by,
                "tipus": "kivalasztottak_kozott",
                "kivalasztott_tipus": ",".join(categories),
                "jsons": "true",
            }
            if page > 1:
                params["oldal"] = str(page)
            response = self._get("torrents.php", **params)
            if "json" not in response.headers.get("content-type", ""):
                if re.search(r"(?i)nincs\s+tal[aá]lat", _plain(response.text)):
                    break
                raise TrackerError("nCore's search gave an unknown HTML answer")
            try:
                document = response.json()
            except json.JSONDecodeError:
                raise TrackerError("nCore's search answer is broken") from None
            if not isinstance(document, Mapping) or not isinstance(document.get("results", []), list):
                raise TrackerError("nCore's search answer changed its form")
            items = [item for item in document.get("results") or [] if isinstance(item, dict)]
            results.extend(items)
            total = _to_int(document.get("total_results"))
            per_page = _to_int(document.get("perpage")) or _to_int(document.get("onpage")) or len(items)
            if not items or not total or len(results) >= total or len(items) < per_page:
                break
        if total > len(results):
            raise TrackerError("nCore's search has more hits than can be checked")
        return results

    def search(self, *, imdb_id: str | None, release_name: str) -> tuple[TrackerMatch, ...]:
        """Every film upload of this title or with this exact name.

        The rules allow several uploads of a film, so a hit is for the operator
        to judge; an identical name is marked.
        """

        categories = (CATEGORY_HUNGARIAN, CATEGORY_FOREIGN)
        found: dict[str, TrackerMatch] = {}
        wanted = _normal_name(release_name)
        hits = self._search_raw(release_name, "name", categories)
        if imdb_id:
            hits += self._search_raw(imdb_id, "imdb", categories)
        for item in hits:
            name = str(item.get("release_name") or "")
            identifier = str(item.get("torrent_id") or name)
            size = _to_int(item.get("size")) or None
            found[identifier] = TrackerMatch(
                name=name,
                url=details_url(int(identifier)) if identifier.isdigit() else "",
                size=size,
                exact=_normal_name(name) == wanted,
            )
        return tuple(found.values())

    def banned_notice(self, token: str, fields: Mapping[str, str]) -> str:
        """nCore's own hint on banned material for this name; empty when nothing matches."""

        try:
            response = self._client.post(
                urljoin(f"{BASE_URL}/", "ajax.php?action=up_live&tiltott=1"),
                data={**self._hidden, **fields, "getUnique": token},
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise TrackerError(f"the ban list check cannot be reached ({type(exc).__name__})") from None
        if _is_login_page(response):
            raise SessionExpired("the nCore cookies have expired: export them again from the browser")
        if response.status_code != 200:
            raise TrackerError(f"the ban list check answered HTTP {response.status_code}")
        return _plain(response.text)

    def _ids_named(self, name: str) -> dict[int, dict[str, Any]] | None:
        wanted = _normal_name(name)
        try:
            hits = self._search_raw(name, "name", (CATEGORY_HUNGARIAN, CATEGORY_FOREIGN))
        except TrackerError:
            return None
        return {
            int(item["torrent_id"]): item
            for item in hits
            if str(item.get("torrent_id", "")).isdigit() and _normal_name(item.get("release_name")) == wanted
        }

    def _find_new(
        self, name: str, before: dict[int, dict[str, Any]] | None, local: bytes
    ) -> tuple[int | None, str]:
        """The upload, when the answer did not show it: one new torrent with this
        name and the same pieces as the one sent.  Never a guess."""

        if before is None or not name:
            return None, "the search before the upload failed, so nothing can be compared"
        problem = "the search found no new torrent with this name"
        for attempt in range(self.find_attempts):
            if attempt:
                self._sleep(self.find_delay)
            after = self._ids_named(name)
            if after is None:
                problem = "the search failed"
                continue
            new = [identifier for identifier in after if identifier not in before]
            if len(new) > 1:
                return None, "several new torrents have this name"
            if not new:
                continue
            try:
                site = self.download_torrent(new[0])
            except TrackerError as exc:
                return None, f"probably uploaded as #{new[0]}, but it cannot be checked: {exc}"
            if not same_content(site, local):
                return None, f"#{new[0]} has this name but other content"
            return new[0], ""
        return None, problem

    def upload(
        self,
        fields: Mapping[str, str],
        files: Mapping[str, tuple[str, bytes, str]],
    ) -> UploadResult:
        payload = {**self._hidden, **{key: str(value) for key, value in fields.items()}}
        # What a browser posts from a textarea.
        payload["szoveg"] = re.sub(r"\r?\n", "\r\n", payload.get("szoveg", ""))
        name = payload.get("torrent_nev", "")
        local = files.get("torrent_fajl", ("", b"", ""))[1]
        before = self._ids_named(name)
        try:
            response = self._client.post(
                urljoin(f"{BASE_URL}/", "upload.php"),
                data=payload,
                files=dict(files),
                headers=self._headers,
                timeout=UPLOAD_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            found, problem = self._find_new(name, before, local)
            if found:
                return UploadResult(accepted=True, torrent_id=found, url=details_url(found), note="found by its name and pieces")
            return UploadResult(errors=(f"the upload request broke off ({type(exc).__name__}); {problem}",))
        if _is_login_page(response):
            raise SessionExpired("the nCore cookies expired during the upload")
        errors = parse_errors(response.text)
        if errors:
            return UploadResult(rejected=True, errors=tuple(errors))
        torrent_id = _response_details_id(response)
        if torrent_id:
            return UploadResult(accepted=True, torrent_id=torrent_id, url=details_url(torrent_id))
        found, problem = self._find_new(name, before, local)
        if found:
            return UploadResult(accepted=True, torrent_id=found, url=details_url(found), note="found by its name and pieces")
        return UploadResult(errors=(f"an unclear answer, HTTP {response.status_code}; {problem}",))

    def download_torrent(self, torrent_id: int) -> bytes:
        """The site's own torrent, with the account's passkey; that is the one to seed."""

        details = self._get("torrents.php", action="details", id=str(torrent_id)).text
        found = re.search(
            rf"action=download&(?:amp;)?id={int(torrent_id)}&(?:amp;)?key=([0-9a-fA-F]{{32}})", details
        ) or _PASSKEY.search(details)
        if not found:
            raise TrackerError("the torrent's page shows no passkey")
        response = self._get("torrents.php", action="download", id=str(torrent_id), key=found.group(1))
        try:
            info_hash(response.content)
        except TorrentError:
            raise TrackerError("the downloaded file is not a torrent") from None
        return response.content
