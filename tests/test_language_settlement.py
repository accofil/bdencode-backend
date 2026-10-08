"""Choosing a retained track's language without stopping on detector noise."""

from __future__ import annotations

from bdencode.media.language import same_language, settle_track_language


def labels(mpls=None, clpi=None, pmt=None):
    return {"mpls": mpls, "clpi": clpi, "pmt": pmt}


def test_agreeing_disc_labels_win_over_a_confident_detection_with_a_warning() -> None:
    settled = settle_track_language(labels("hun", "hun"), "eng", 0.93)
    assert settled.language == "hun" and not settled.stop
    assert "kept although the language detection heard eng" in settled.warning


def test_a_matching_or_related_detection_needs_no_warning() -> None:
    assert settle_track_language(labels("zho", "zho"), "yue", 0.95).warning is None
    assert settle_track_language(labels("hrv"), "srp", 0.9).warning is None
    assert same_language("nob", "nor")


def test_mpls_and_clpi_outvote_a_dissenting_pmt() -> None:
    assert settle_track_language(labels("fra", "fra", "eng")).language == "fra"


def test_disagreeing_labels_are_settled_by_a_confident_detection() -> None:
    settled = settle_track_language(labels("eng", "deu"), "deu", 0.92)
    assert settled.language == "deu" and "chose deu" in settled.warning


def test_disagreeing_labels_without_a_usable_detection_use_the_playlist_label() -> None:
    settled = settle_track_language(labels("eng", "deu"), "deu", 0.4)
    assert settled.language == "eng" and not settled.stop and settled.warning


def test_only_a_confident_detection_against_contradicting_labels_stops() -> None:
    assert settle_track_language(labels("eng", "deu"), "jpn", 0.95).stop


def test_unlabelled_tracks_use_the_detection_or_stay_und() -> None:
    assert settle_track_language(labels(), "ita", 0.95).language == "ita"
    weak = settle_track_language(labels(), "ita", 0.8)
    assert weak.language == "ita" and weak.warning
    unknown = settle_track_language(labels())
    assert unknown.language is None and not unknown.stop and "und" in unknown.warning
