"""Built-in presets that follow Aither encoding practice."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bdencode.api import create_app
from bdencode.db import Database
from bdencode.media.aither_presets import aither_preset_settings, aither_presets
from bdencode.media.profiles import recommended_profile


@pytest.mark.parametrize("encoder", ["x264", "x265"])
def test_every_preset_is_a_valid_profile_for_its_encoder(encoder: str) -> None:
    presets = aither_presets(encoder)
    assert {item.content for item in presets} == {"grain", "clean", "animation"}
    for item in presets:
        settings = recommended_profile(
            encoder, detail_level="pro", overrides=aither_preset_settings(encoder, item.id)
        )
        assert settings.encoder.value == encoder


def test_grain_presets_keep_grain_and_clean_presets_use_the_ratecontrol_trees() -> None:
    uhd_grain = recommended_profile("x265", detail_level="pro", overrides=aither_preset_settings("x265", "aither_uhd_grain")).private_params()
    assert (uhd_grain["sao"], uhd_grain["cutree"], uhd_grain["strong-intra-smoothing"]) == (0, 0, 0)
    assert uhd_grain["deblock"] == "-3,-3" and uhd_grain["psy-rd"] >= 1.8

    uhd_clean = recommended_profile("x265", detail_level="pro", overrides=aither_preset_settings("x265", "aither_uhd_clean")).private_params()
    assert (uhd_clean["sao"], uhd_clean["cutree"]) == (0, 1)

    bd_grain = recommended_profile("x264", detail_level="pro", overrides=aither_preset_settings("x264", "aither_bd_quality_grain"))
    params = bd_grain.private_params()
    assert (params["mbtree"], params["fast-pskip"], params["dct-decimate"], params["open-gop"]) == (0, 0, 0, 0)
    assert (bd_grain.ref, bd_grain.bframes, params["deblock"]) == (4, 16, "-3,-3")

    bd_clean = recommended_profile("x264", detail_level="pro", overrides=aither_preset_settings("x264", "aither_bd_quality_clean"))
    assert bd_clean.private_params()["mbtree"] == 1 and bd_clean.qcomp >= 0.7 and bd_clean.rc_lookahead == 250


def test_switching_presets_leaves_nothing_behind() -> None:
    grain = aither_preset_settings("x265", "aither_uhd_grain")
    animation = aither_preset_settings("x265", "aither_uhd_animation")
    assert set(grain) == set(animation)
    assert grain["cutree"] is False and animation["cutree"] is True


def test_the_api_lists_the_presets_with_concrete_settings(tmp_path: Path) -> None:
    client = TestClient(create_app(Database(tmp_path / "state.sqlite3")))

    body = client.get("/api/v1/profiles/x265/aither-presets").json()
    assert body["encoder"] == "x265" and body["requires_operator_confirmation"] is True
    labels = {item["id"]: item for item in body["presets"]}
    assert labels["aither_uhd_grain"]["settings"]["sao"] is False
    assert labels["aither_uhd_grain"]["crf_hint"]
    assert client.get("/api/v1/profiles/x264/aither-presets").json()["presets"][0]["encoder"] == "x264"
