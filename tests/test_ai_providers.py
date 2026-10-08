"""Claude as a second adviser, the provider choice and the key requests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from bdencode.ai_recommendation import (
    ANTHROPIC_FALLBACK_BETA,
    AIRecommendationError,
    AIRecommendationService,
    AIRecommendationUnavailable,
    RecommendationContext,
    anthropic_output_schema,
    convert_text_value,
)
from bdencode.ai_settings import (
    AIPreferences,
    key_management_view,
    load_preferences,
    save_preferences,
    submit_credential_request,
    validate_api_key,
)
from bdencode.api import create_app
from bdencode.config import Settings
from bdencode.db import Database
from bdencode.media.profiles import DetailLevel, VideoEncoder, recommended_profile

ANTHROPIC_KEY = "sk-ant-api03-" + "a" * 40
OPENAI_KEY = "sk-proj-" + "b" * 40


def _context() -> RecommendationContext:
    return RecommendationContext(
        encoder=VideoEncoder.X264,
        detail_level=DetailLevel.ADVANCED,
        content_type="film",
        scan_facts={"disc_kind": "bd", "video": {"width": 1920, "height": 1080}},
        base_settings=recommended_profile("x264", detail_level=DetailLevel.ADVANCED),
        quality_priority="maximum",
        target_size_gib=None,
        genre=None,
        prompt="Őrizze meg a szemcsét.",
    )


def _claude_document(settings: list[dict[str, str]]) -> dict[str, object]:
    return {
        "settings": settings,
        "temporal_filter": "progressive",
        "summary": "Szemcsemegőrző profil.",
        "rationale": ["Alacsonyabb CRF."],
        "warnings": [],
        "confidence": 0.8,
    }


class FakeMessages:
    def __init__(self, document: object, stop_reason: str = "end_turn") -> None:
        self.document = document
        self.stop_reason = stop_reason
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            model="claude-opus-5-5",
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=json.dumps(self.document)),
            ],
        )


def _claude_service(
    messages: FakeMessages, tmp_path: Path, keys: dict[str, str] | None = None
) -> tuple[AIRecommendationService, list[tuple[str, float]]]:
    created: list[tuple[str, float]] = []
    available = keys if keys is not None else {"anthropic-api-key": ANTHROPIC_KEY}

    def factory(api_key: str, timeout: float) -> SimpleNamespace:
        created.append((api_key, timeout))
        return SimpleNamespace(beta=SimpleNamespace(messages=messages))

    return (
        AIRecommendationService(
            credential_loader=lambda name: available.get(name, ""),
            anthropic_client_factory=factory,
            preferences_path=tmp_path / "ai-settings.json",
        ),
        created,
    )


def test_claude_schema_has_no_unions_or_numeric_bounds() -> None:
    schema, fields = anthropic_output_schema(VideoEncoder.X265, DetailLevel.PRO)
    text = json.dumps(schema)

    assert "crf" in fields and "sao" in fields
    assert "encoder" not in fields and "hdr10" not in fields
    assert '"null"' not in text and "anyOf" not in text
    assert "minimum" not in text and "maximum" not in text
    item = schema["properties"]["settings"]["items"]
    assert item["additionalProperties"] is False
    assert item["properties"]["field"]["enum"] == list(fields)


def test_claude_recommendation_is_converted_and_validated_locally(tmp_path: Path) -> None:
    messages = FakeMessages(
        _claude_document(
            [
                {"field": "crf", "value": "16.5"},
                {"field": "preset", "value": "slower"},
                {"field": "tune", "value": "grain"},
                {"field": "bframes", "value": "99"},  # above the maximum: dropped
            ]
        )
    )
    service, created = _claude_service(messages, tmp_path)

    result = service.recommend(_context())

    assert created == [(ANTHROPIC_KEY, 180.0)]
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["betas"] == [ANTHROPIC_FALLBACK_BETA]
    assert call["extra_body"] == {"fallbacks": "default"}
    assert call["output_config"]["effort"] == "high"
    assert call["output_config"]["format"]["type"] == "json_schema"
    model_input = json.loads(call["messages"][0]["content"])
    briefs = {item["name"]: item for item in model_input["allowed_override_fields"]}
    assert briefs["crf"]["value_type"] == "number" and "maximum" in briefs["crf"]
    assert result.provider == "anthropic"
    assert result.source == "anthropic_messages_api"
    assert result.settings["crf"] == 16.5
    assert result.settings["preset"] == "slower"
    assert result.settings["qcomp"] == 0.75  # grain coherence from the local builder
    assert result.settings["bframes"] != 99
    assert any("bframes" in warning for warning in result.warnings)


def test_claude_refusal_and_bad_shapes_are_rejected(tmp_path: Path) -> None:
    refused, _ = _claude_service(FakeMessages(_claude_document([]), "refusal"), tmp_path)
    with pytest.raises(AIRecommendationError, match="nem adott javaslatot"):
        refused.recommend(_context())

    unknown_field, _ = _claude_service(
        FakeMessages(_claude_document([{"field": "encoder", "value": "x265"}])), tmp_path
    )
    with pytest.raises(AIRecommendationError, match="invalid shape"):
        unknown_field.recommend(_context())


def test_claude_api_errors_name_the_problem_without_the_key(tmp_path: Path) -> None:
    class Rejected(Exception):
        status_code = 401

    class Failing:
        def create(self, **_kwargs: object) -> None:
            raise Rejected("unauthorized")

    service, _ = _claude_service(Failing(), tmp_path)  # type: ignore[arg-type]
    with pytest.raises(AIRecommendationError) as error:
        service.recommend(_context())
    assert "elutasította az API-kulcsot" in str(error.value)
    assert ANTHROPIC_KEY not in str(error.value)


def test_text_values_follow_the_field_types() -> None:
    assert convert_text_value({"value_type": "boolean"}, "TRUE") is True
    assert convert_text_value({"value_type": "integer", "minimum": 0}, "4.0") == 4
    assert convert_text_value({"value_type": "enum", "choices": ("a", "b")}, " b ") == "b"
    for field, text in (
        ({"value_type": "integer"}, "4.5"),
        ({"value_type": "number", "maximum": 51}, "60"),
        ({"value_type": "number"}, "nan"),
        ({"value_type": "enum", "choices": ("a",)}, "c"),
        ({"value_type": "boolean"}, "yes"),
    ):
        with pytest.raises(ValueError):
            convert_text_value(field, text)


def test_provider_choice_follows_preferences_and_configured_keys(tmp_path: Path) -> None:
    messages = FakeMessages(_claude_document([]))
    service, _ = _claude_service(messages, tmp_path)

    # No saved choice: the first provider with a key, here Claude.
    status = service.status()
    assert status["provider"] == "anthropic" and status["configured"] is True
    assert [item["id"] for item in status["providers"]] == ["openai", "anthropic"]
    assert status["providers"][0]["configured"] is False

    save_preferences(
        tmp_path / "ai-settings.json",
        AIPreferences(default_provider="openai", anthropic_model="claude-sonnet-5-5"),
    )
    status = service.status()
    assert status["provider"] == "openai" and status["configured"] is False
    assert status["providers"][1]["model"] == "claude-sonnet-5-5"
    with pytest.raises(AIRecommendationUnavailable, match="OpenAI API-kulcs"):
        service.recommend(_context())
    # A per-request choice overrides the saved default.
    service.recommend(_context(), "anthropic")
    assert messages.calls[-1]["model"] == "claude-sonnet-5-5"


def test_preferences_reject_bad_model_names_and_survive_a_broken_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        AIPreferences(openai_model="gpt; rm -rf /")
    assert AIPreferences(openai_model="  ").openai_model is None
    path = tmp_path / "ai-settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_preferences(path) == AIPreferences()


def test_api_keys_are_checked_per_provider() -> None:
    assert validate_api_key("anthropic", f"  {ANTHROPIC_KEY}\n") == ANTHROPIC_KEY
    assert validate_api_key("openai", OPENAI_KEY) == OPENAI_KEY
    for provider, key in (
        ("anthropic", OPENAI_KEY),
        ("openai", ANTHROPIC_KEY),
        ("openai", "sk-short"),
        ("openai", "sk-" + "a" * 30 + " x"),
    ):
        with pytest.raises(ValueError):
            validate_api_key(provider, key)  # type: ignore[arg-type]


def test_a_key_request_is_a_private_file_the_helper_glob_matches(tmp_path: Path) -> None:
    request_id = submit_credential_request(tmp_path, "anthropic", "set", ANTHROPIC_KEY)

    files = list(tmp_path.iterdir())
    assert [item.name for item in files] == [f"credential-request-{request_id}.json"]
    document = json.loads(files[0].read_text(encoding="utf-8"))
    assert document == {
        "schema_version": 1,
        "request_id": request_id,
        "credential": "anthropic-api-key",
        "action": "set",
        "value": ANTHROPIC_KEY,
    }
    if os.name == "posix":
        assert files[0].stat().st_mode & 0o777 == 0o600


def test_key_management_reports_helper_results_without_keys(tmp_path: Path) -> None:
    status = tmp_path / "status.json"
    status.write_text(
        json.dumps(
            {"results": [{"request_id": "abc", "state": "applied", "value": "leak", "credential": "openai-api-key"}]}
        ),
        encoding="utf-8",
    )
    view = key_management_view(
        {"BDENCODE_CREDENTIAL_REQUEST_DIR": str(tmp_path), "BDENCODE_CREDENTIAL_STATUS_PATH": str(status)}
    )
    assert view["available"] is True
    assert view["results"] == [{"request_id": "abc", "state": "applied", "credential": "openai-api-key"}]
    assert key_management_view({})["available"] is False


def test_system_page_endpoints_save_choices_and_queue_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("BDENCODE_CREDENTIAL_REQUEST_DIR", str(runtime))
    monkeypatch.setenv("BDENCODE_CREDENTIAL_STATUS_PATH", str(tmp_path / "status.json"))
    source = tmp_path / "source"
    source.mkdir()
    settings = Settings(data_root=tmp_path / "data", source_roots=(source,)).validate()
    settings.create_directories()
    service = AIRecommendationService(
        credential_loader=lambda _name: "",
        preferences_path=settings.state_root / "ai-settings.json",
    )
    with TestClient(
        create_app(Database(tmp_path / "ai.sqlite3"), settings=settings, ai_recommender=service)
    ) as client:
        saved = client.put(
            "/api/v1/system/ai-settings",
            json={"default_provider": "anthropic", "anthropic_model": "claude-sonnet-5-5"},
        )
        assert saved.status_code == 200
        assert saved.json()["provider"] == "anthropic"
        assert saved.json()["key_management"]["available"] is True

        rejected = client.put(
            "/api/v1/system/ai-credentials/anthropic", json={"api_key": OPENAI_KEY}
        )
        assert rejected.status_code == 422
        assert OPENAI_KEY not in rejected.text
        assert list(runtime.iterdir()) == []

        accepted = client.put(
            "/api/v1/system/ai-credentials/anthropic", json={"api_key": ANTHROPIC_KEY}
        )
        assert accepted.status_code == 202
        assert ANTHROPIC_KEY not in accepted.text
        request_id = accepted.json()["request_id"]
        assert (runtime / f"credential-request-{request_id}.json").is_file()

        deleted = client.delete("/api/v1/system/ai-credentials/openai")
        assert deleted.status_code == 202
        assert len(list(runtime.iterdir())) == 2

        monkeypatch.delenv("BDENCODE_CREDENTIAL_REQUEST_DIR")
        monkeypatch.delenv("RUNTIME_DIRECTORY", raising=False)
        unavailable = client.delete("/api/v1/system/ai-credentials/openai")
        assert unavailable.status_code == 422
        assert unavailable.json()["code"] == "ai_key_management_unavailable"


def test_the_real_sdk_sends_the_expected_request() -> None:
    """Wire-level check against the installed SDK (CI installs it)."""

    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    seen: dict[str, object] = {}
    document = _claude_document([{"field": "crf", "value": "17"}])

    def handler(request):  # type: ignore[no-untyped-def]
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": json.dumps(document)}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        )

    def factory(api_key: str, timeout: float):  # type: ignore[no-untyped-def]
        return anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
        )

    service = AIRecommendationService(
        credential_loader=lambda name: ANTHROPIC_KEY if name == "anthropic-api-key" else "",
        anthropic_client_factory=factory,
    )
    result = service.recommend(_context(), "anthropic")

    assert "/v1/messages" in str(seen["url"])
    headers = seen["headers"]
    assert headers["x-api-key"] == ANTHROPIC_KEY  # type: ignore[index]
    assert ANTHROPIC_FALLBACK_BETA in headers["anthropic-beta"]  # type: ignore[index]
    body = seen["body"]
    assert body["fallbacks"] == "default"  # type: ignore[index]
    assert body["output_config"]["format"]["type"] == "json_schema"  # type: ignore[index]
    assert body["model"] == "claude-opus-5-5"  # type: ignore[index]
    assert result.settings["crf"] == 17
