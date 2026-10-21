"""Which language a subtitle stream is written in, read from its own text.

Disc and Matroska language tags are often missing or wrong (a disc can label
three PGS streams "ger" when one is English).  The selection-time track
analysis therefore reads a few captions of every subtitle stream:

* PGS (bitmap) captions are drawn onto a canvas with FFmpeg and read with
  tesseract.  The installed models only need to cover the Latin alphabet:
  the language is told from the words, not from the OCR model.
* Text subtitles (SubRip, ASS, WebVTT) are converted to plain text.

The text is then matched against short lists of the most frequent words of
each language.  Captions are short, so a result needs a minimum number of
words and a clear lead over the runner-up; otherwise it is "unknown".
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

TEXT_SUBTITLE_CODECS = frozenset({"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"})
BITMAP_SUBTITLE_CODECS = frozenset({"hdmv_pgs_subtitle", "pgssub"})
# The OCR models installed on the hosts (Latin alphabet); more can be added.
OCR_LANGUAGES = "eng+hun"
# Captions read per PGS stream (spread over the sampled windows).
OCR_CAPTIONS_PER_STREAM = 12
MIN_WORDS = 12
# The winner needs this share of the two best scores to count.
MIN_LEAD = 0.62

# The most frequent short words of each language (ISO 639-2/T codes), chosen
# so that the lists overlap as little as possible.
STOPWORDS: dict[str, frozenset[str]] = {
    code: frozenset(text.split())
    for code, text in {
        "eng": (
            "the and you to is it that of what this in me my your we for be have not are on don't i'm "
            "with do was he she they there just know no yes yeah okay ok get got can if so all here "
            "right now come go want like about how why who him her them us our oh hey please thank thanks "
            "sorry well out up one would could will there's that's it's you're we're can't didn't"
        ),
        "deu": (
            "und der die das ist nicht ich du sie es wir ein eine einen zu mit auf was den dem des bin "
            "hast haben hat sind wie aber auch noch nur ja nein danke bitte mich dich mir dir uns euch "
            "ihr er wo warum wer wenn dann doch schon hier jetzt mal so gut kann muss will weiß weiss "
            "nichts alles bis ins im am vom zum zur oder kein keine gibt geht komm los mein dein "
            "über uber für fur können konnen müssen mussen schön schon gehen machen sagen"
        ),
        "fra": (
            "le la les et est pas je vous tu il elle nous un une que qui des du dans pour sur ce c'est "
            "mais avec ne suis oui non merci moi toi lui leur ils elles on ça ça va bien très tres "
            "tout rien quoi où ou comment pourquoi qu'il j'ai je suis n'est plus fait faire peut "
            "veux sais vais être etre avoir allez viens alors aussi ici là"
        ),
        "spa": (
            "el la los las y es no que de un una por para con lo se te mi está esta qué que yo tu pero "
            "eso esto muy sí si gracias hola bien nada todo aquí aqui ahora vamos tengo tiene hay "
            "estoy eres soy sé creo quiero puedo cómo como dónde donde porque también tambien me le "
            "nos les su sus al del"
        ),
        "ita": (
            "il lo la gli le e è non che di un una per con mi ti si sono questo cosa ma io tu ho hai "
            "bene sì grazie ciao niente tutto qui adesso andiamo cosa perché perche come dove anche "
            "molto sei siamo voglio posso devo fatto della dello delle nel nella del al alla"
        ),
        "por": (
            "o a os as e é não nao que de um uma para com se me eu você voce isso está esta mas muito "
            "do da em sim obrigado obrigada olá tudo nada aqui agora vamos tenho tem estou sou sei "
            "quero posso como onde porque também tambem ele ela nós nos"
        ),
        "nld": (
            "de het een en is niet ik je jij we wat dat van op te met zijn maar ook nog hij zij er "
            "ja nee dank bedankt hallo goed alles niets hier nu kom gaan ben heb hebt weet wil kan "
            "moet waar waarom hoe wie mij jou ons jullie zo dit deze"
        ),
        "hun": (
            "a az és nem hogy is egy van ez de mi te én meg csak már mit itt ott jó ne vagy volt lesz "
            "igen köszönöm koszonom kérem kerem szia hello minden semmi most gyere menj tudom akarom "
            "kell lehet miért miert hol hogyan nekem neked engem téged teged ezt azt ki mikor"
        ),
        "pol": (
            "i nie to się sie jest że ze w na z co jak ale tak ja ty mi go już juz czy do tego "
            "dziękuję dziekuje proszę prosze cześć czesc dobrze wszystko nic tutaj teraz chodź "
            "wiem chcę chce mogę moge muszę gdzie dlaczego mnie ciebie nas jestem jesteś"
        ),
        "ces": (
            "a je to se že ze na v ne jsem jsi co jak ale tak už uz mi ti by bylo ano děkuji dekuji "
            "prosím prosim ahoj dobře dobre všechno nic tady teď ted pojď vím chci můžu musím kde "
            "proč proc mě tě nás jsme jste"
        ),
        "swe": (
            "och att det är jag inte en som på med har du vi för de så vad den här ja nej tack hej "
            "bra allt inget nu kom gå vet vill kan måste var varför hur vem mig dig oss ni"
        ),
        "dan": (
            "og at det er jeg ikke en som på med har du vi for de så hvad den her ja nej tak hej "
            "godt alt intet nu kom gå ved vil kan skal hvor hvorfor hvordan hvem mig dig os jer"
        ),
        "nor": (
            "og at det er jeg ikke en som på med har du vi for de så hva den her ja nei takk hei "
            "bra alt ingenting nå kom gå vet vil kan må hvor hvorfor hvordan hvem meg deg oss dere"
        ),
        "fin": (
            "ja on ei se että etta mitä mita minä mina sinä sina hän han me te he tämä tama kun mutta "
            "niin olen oli kyllä kylla kiitos hei hyvä hyva kaikki mitään nyt tule mennään tiedän "
            "haluan voin pitää missä miksi miten kuka minua sinua meitä olet olemme"
        ),
        "tur": (
            "ve bir bu da de ne ben sen o biz için icin ile çok cok mi mı değil degil var yok ama "
            "evet hayır hayir teşekkürler tesekkurler merhaba iyi her şey hiç simdi şimdi gel git "
            "biliyorum istiyorum neden nasıl nasil kim beni seni bizi"
        ),
        "ron": (
            "și si nu că ca de la în in un o pe este ce eu tu el ea noi sunt dar cu da mulțumesc "
            "multumesc bună buna totul nimic aici acum vino știu stiu vreau pot trebuie unde de ce "
            "cum cine mine tine noi"
        ),
    }.items()
}


def words(text: str) -> list[str]:
    return [word for word in re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text.lower()) if len(word) > 0]


def identify_text_language(text: str) -> dict[str, Any]:
    """The language of ``text`` by its frequent words, or ``unknown``."""

    tokens = words(text)
    if len(tokens) < MIN_WORDS:
        return {"status": "unknown", "reason": "too_little_text", "words": len(tokens)}
    scores = {
        code: sum(1 for token in tokens if token in vocabulary) / len(tokens)
        for code, vocabulary in STOPWORDS.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    (best, best_score), (_second, second_score) = ranked[0], ranked[1]
    if best_score <= 0:
        return {"status": "unknown", "reason": "no_known_words", "words": len(tokens)}
    lead = best_score / (best_score + second_score) if best_score + second_score else 1.0
    if lead < MIN_LEAD:
        return {"status": "unknown", "reason": "ambiguous", "words": len(tokens), "candidates": [best, _second]}
    # Confidence grows with the lead and with the amount of text.
    confidence = min(0.99, lead * min(1.0, 0.6 + len(tokens) / 250))
    return {
        "status": "detected",
        "iso639_2t": best,
        "confidence": round(confidence, 3),
        "words": len(tokens),
    }


def subtitle_probe_command(path: Path, *, ffprobe: str = "ffprobe") -> list[str]:
    """Each packet's time and size (captions are the large packets)."""

    return [
        ffprobe, "-v", "error", "-show_entries", "packet=pts_time,size",
        "-of", "csv=p=0", str(path),
    ]


def subtitle_size_command(path: Path, *, ffprobe: str = "ffprobe") -> list[str]:
    return [ffprobe, "-v", "error", "-select_streams", "s:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)]


def parse_packets(csv: str) -> list[tuple[float, int]]:
    """``(time, size)`` per packet from :func:`subtitle_probe_command`."""

    packets: list[tuple[float, int]] = []
    for line in csv.splitlines():
        fields = [field.strip() for field in line.split(",") if field.strip()]
        if not fields:
            continue
        try:
            size = int(fields[-1])
            time = float(fields[0]) if len(fields) > 1 else 0.0
        except ValueError:
            continue
        packets.append((time, size))
    return packets


def parse_size(csv: str) -> tuple[int, int] | None:
    for line in csv.splitlines():
        try:
            width, height = (int(value) for value in line.strip().split(",")[:2])
        except ValueError:
            continue
        if width > 0 and height > 0:
            return width, height
    return None


def render_caption_command(
    path: Path, time: float, size: tuple[int, int], out_png: Path, *, ffmpeg: str = "ffmpeg"
) -> list[str]:
    """Draw the caption shown at ``time`` as dark text on white (what OCR reads best)."""

    # Seeking inside the subtitle input loses the caption: the canvas runs on
    # the window's own timeline instead and the frame just after the caption
    # appears is taken.
    width, height = size
    at = max(0.0, time) + 0.2
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=5:d={at + 1:.3f}",
        "-i", str(path),
        "-filter_complex",
        f"[0:v][1:s:0]overlay=eof_action=pass,select='gte(t,{at:.3f})',format=gray,negate",
        "-frames:v", "1", "-fps_mode", "passthrough", str(out_png),
    ]


def ocr_command(png: Path, *, tesseract: str = "tesseract", languages: str = OCR_LANGUAGES) -> list[str]:
    return [tesseract, str(png), "stdout", "-l", languages, "--psm", "6"]


def sup_command(path: Path, out_sup: Path, *, ffmpeg: str = "ffmpeg") -> list[str]:
    """The raw PGS stream of a window (FFmpeg's own caption drawing loses most
    captions of a cut-out window: they refer to objects defined before it)."""

    return [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(path), "-map", "0:s:0", "-c", "copy", "-f", "sup", str(out_sup)]


def _decode_rle(data: bytes, width: int, height: int) -> bytearray:
    """PGS run-length data -> one palette index per pixel."""

    pixels = bytearray(width * height)
    x = y = 0
    position = 0
    while position < len(data) and y < height:
        value = data[position]
        position += 1
        if value:
            count, colour = 1, value
        else:
            if position >= len(data):
                break
            flags = data[position]
            position += 1
            if flags == 0:
                x, y = 0, y + 1
                continue
            count = flags & 0x3F
            if flags & 0x40:
                if position >= len(data):
                    break
                count = (count << 8) | data[position]
                position += 1
            colour = 0
            if flags & 0x80:
                if position >= len(data):
                    break
                colour = data[position]
                position += 1
        end = min(x + count, width)
        if colour and y < height:
            start = y * width
            pixels[start + x:start + end] = bytes([colour]) * (end - x)
        x = end
    return pixels


def pgs_captions(sup: bytes, limit: int = 64) -> list[tuple[float, int, int, bytes]]:
    """``(time, width, height, grey pixels)`` of the caption bitmaps of a .sup.

    The pixels are dark text on white (what tesseract reads best): the grey
    value is the palette entry's luminance weighted by its opacity, inverted.
    """

    palette = [255] * 256
    pending: dict[int, dict[str, Any]] = {}
    captions_found: list[tuple[float, int, int, bytes]] = []
    position = 0
    while position + 13 <= len(sup) and sup[position:position + 2] == b"PG":
        pts = int.from_bytes(sup[position + 2:position + 6], "big") / 90000
        kind = sup[position + 10]
        size = int.from_bytes(sup[position + 11:position + 13], "big")
        segment = sup[position + 13:position + 13 + size]
        position += 13 + size
        if kind == 0x14:  # palette: id, version, then id, Y, Cr, Cb, alpha per entry
            for offset in range(2, len(segment) - 4, 5):
                entry, luma, alpha = segment[offset], segment[offset + 1], segment[offset + 4]
                palette[entry] = 255 - (luma * alpha) // 255
        elif kind == 0x15 and len(segment) >= 4:  # object (may span segments)
            object_id = int.from_bytes(segment[0:2], "big")
            sequence = segment[3]
            if sequence & 0x80 and len(segment) >= 11:
                width = int.from_bytes(segment[7:9], "big")
                height = int.from_bytes(segment[9:11], "big")
                pending[object_id] = {"width": width, "height": height, "data": bytearray(segment[11:]), "pts": pts}
            elif object_id in pending:
                pending[object_id]["data"] += segment[4:]
            if sequence & 0x40 and object_id in pending:
                item = pending.pop(object_id)
                width, height = item["width"], item["height"]
                if 0 < width <= 4096 and 0 < height <= 2304:
                    indexes = _decode_rle(bytes(item["data"]), width, height)
                    grey = bytes(palette[index] if index else 255 for index in indexes)
                    captions_found.append((item["pts"], width, height, grey))
                    if len(captions_found) >= limit:
                        break
    return captions_found


def write_pgm(path: Path, width: int, height: int, grey: bytes, *, margin: int = 16) -> None:
    """A binary greyscale image (tesseract reads PGM) with a white margin."""

    full_width = width + 2 * margin
    rows = [b"\xff" * full_width] * margin
    for row in range(height):
        rows.append(b"\xff" * margin + grey[row * width:(row + 1) * width] + b"\xff" * margin)
    rows += [b"\xff" * full_width] * margin
    path.write_bytes(f"P5\n{full_width} {height + 2 * margin}\n255\n".encode("ascii") + b"".join(rows))


def text_subtitle_command(path: Path, *, ffmpeg: str = "ffmpeg") -> list[str]:
    return [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:s:0", "-f", "srt", "-"]


_SRT_TIMING = re.compile(r"^\d+:\d\d:\d\d[,.]\d+\s*-->")
_TAGS = re.compile(r"<[^>]+>|\{[^}]*\}")


def srt_text(document: str) -> str:
    """The caption text of an SRT document: no numbers, timings or tags."""

    lines = []
    for line in document.splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit() or _SRT_TIMING.match(stripped):
            continue
        lines.append(_TAGS.sub("", stripped))
    return "\n".join(lines)


def spread(items: Sequence[Any], count: int) -> list[Any]:
    if len(items) <= count:
        return list(items)
    step = (len(items) - 1) / (count - 1) if count > 1 else 0
    return [items[round(index * step)] for index in range(count)]


def captions(packets: Iterable[tuple[float, int]], min_bytes: int) -> list[float]:
    """The times of the captions (large packets) of one window."""

    return [time for time, size in packets if size >= min_bytes]


def summarise(result: Mapping[str, Any], method: str, sample: str) -> dict[str, Any]:
    return {**result, "method": method, "sample": sample.replace("\n", " ")[:160]}


__all__ = [
    "BITMAP_SUBTITLE_CODECS",
    "OCR_CAPTIONS_PER_STREAM",
    "OCR_LANGUAGES",
    "STOPWORDS",
    "TEXT_SUBTITLE_CODECS",
    "captions",
    "identify_text_language",
    "ocr_command",
    "parse_packets",
    "parse_size",
    "render_caption_command",
    "spread",
    "srt_text",
    "subtitle_probe_command",
    "subtitle_size_command",
    "summarise",
    "text_subtitle_command",
    "words",
]
