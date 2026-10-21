"""Subtitle language from the captions' own text: PGS decoding, OCR input, word lists."""

from __future__ import annotations

from pathlib import Path

from bdencode.media.subtitle_language import (
    identify_text_language,
    parse_packets,
    pgs_captions,
    render_caption_command,
    srt_text,
    sup_command,
    write_pgm,
)


def segment(kind: int, payload: bytes, pts: float = 1.0) -> bytes:
    ticks = int(pts * 90000).to_bytes(4, "big")
    return b"PG" + ticks + b"\x00\x00\x00\x00" + bytes([kind]) + len(payload).to_bytes(2, "big") + payload


def caption_sup(pts: float = 12.5) -> bytes:
    """A 4x2 caption: a white line over a transparent one."""

    palette = segment(0x14, bytes([0, 0]) + bytes([1, 235, 128, 128, 255]), pts)
    # Line 1: four pixels of colour 1; line 2: four transparent pixels.
    rle = bytes([0x00, 0x84, 0x01, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00])
    header = (7).to_bytes(2, "big") + bytes([0, 0xC0]) + (len(rle) + 4).to_bytes(3, "big")
    obj = segment(0x15, header + (4).to_bytes(2, "big") + (2).to_bytes(2, "big") + rle, pts)
    return palette + obj + segment(0x80, b"", pts)


def test_a_pgs_caption_becomes_dark_text_on_white() -> None:
    ((time, width, height, grey),) = pgs_captions(caption_sup())

    assert (time, width, height) == (12.5, 4, 2)
    assert grey[:4] == bytes([255 - 235] * 4)  # the caption: dark
    assert grey[4:] == b"\xff" * 4  # transparent: white


def test_an_object_split_over_two_segments_is_joined() -> None:
    palette = segment(0x14, bytes([0, 0, 1, 235, 128, 128, 255]))
    rle = bytes([0x00, 0x84, 0x01, 0x00, 0x00])
    first = segment(0x15, (1).to_bytes(2, "big") + bytes([0, 0x80]) + (9).to_bytes(3, "big") + (4).to_bytes(2, "big") + (1).to_bytes(2, "big") + rle[:2])
    rest = segment(0x15, (1).to_bytes(2, "big") + bytes([0, 0x40]) + rle[2:])

    ((_time, width, height, grey),) = pgs_captions(palette + first + rest)

    assert (width, height) == (4, 1) and grey == bytes([20] * 4)


def test_the_image_is_a_padded_greyscale_pgm(tmp_path: Path) -> None:
    image = tmp_path / "caption.pgm"
    write_pgm(image, 4, 2, bytes(8), margin=2)

    data = image.read_bytes()
    assert data.startswith(b"P5\n8 6\n255\n")
    assert len(data) == len(b"P5\n8 6\n255\n") + 8 * 6


def test_words_tell_the_language_of_ocr_text() -> None:
    # Real OCR output of The Florist (2026) PGS captions, umlauts lost.
    german = "Wirklich? Ja. Danke. Ja. Cooler Laden ubrigens. Und danke. Tur fallt ins Schloss. Fick dich. Leck mich. Bis dann, Leute!"
    assert identify_text_language(german)["iso639_2t"] == "deu"
    assert identify_text_language("What are you doing here? I don't know. Come on, we have to go now. Thank you, it's okay.")["iso639_2t"] == "eng"
    assert identify_text_language("Qu'est-ce que tu fais ici ? Je ne sais pas. Allez, on y va. Merci. C'est bon, je suis là.")["iso639_2t"] == "fra"
    assert identify_text_language("Mit csinálsz itt? Nem tudom. Gyere, most mennünk kell. Köszönöm. Semmi baj, itt vagyok veled.")["iso639_2t"] == "hun"


def test_too_little_text_stays_unknown() -> None:
    result = identify_text_language("Ja. Danke.")
    assert result["status"] == "unknown" and result["reason"] == "too_little_text"


def test_srt_text_keeps_only_the_captions() -> None:
    document = "1\n00:00:01,000 --> 00:00:02,000\n<i>Hello</i> there\n\n2\n00:00:03,000 --> 00:00:04,500\n{\\an8}General Kenobi\n"
    assert srt_text(document) == "Hello there\nGeneral Kenobi"


def test_packets_give_time_and_size() -> None:
    assert parse_packets("1.838000,5883\n2.964000,30\nbad\n") == [(1.838, 5883), (2.964, 30)]


def test_commands_read_only_the_window_file(tmp_path: Path) -> None:
    window = tmp_path / "subtitle-4608.mks"
    assert sup_command(window, tmp_path / "x.sup")[-3:] == ["-f", "sup", str(tmp_path / "x.sup")]
    render = render_caption_command(window, 9.6, (1920, 1080), tmp_path / "c.png")
    assert "-ss" not in render  # seeking inside the window loses the caption
