"""Image-host request contracts shared by ImgBB, Catbox and Freeimage."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bdencode import __version__
from bdencode.qc.catbox import CatboxClient
from bdencode.qc.freeimage import FreeimageClient
from bdencode.qc.image_upload import (
    UPLOAD_USER_AGENT,
    ImageUploadError,
    is_permanent_http_rejection,
)
from bdencode.qc.imgbb import ImgBBClient

PNG = b"\x89PNG\r\n\x1a\nuser-agent-contract-png"


@pytest.mark.parametrize(
    ("status", "permanent"),
    [(400, True), (401, True), (403, True), (413, True), (408, False), (429, False), (500, False), (503, False)],
)
def test_only_definitive_client_errors_are_permanent(
    tmp_path: Path, status: int, permanent: bool
) -> None:
    path = tmp_path / "proof.png"
    path.write_bytes(PNG)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="rejected")

    uploader = CatboxClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ImageUploadError) as raised:
        uploader.upload_png(path)
    assert raised.value.permanent is permanent
    assert is_permanent_http_rejection(status) is permanent


def test_the_user_agent_names_the_application_and_its_version() -> None:
    assert UPLOAD_USER_AGENT.startswith(f"BDEncode/{__version__} ")
    assert "python-httpx" not in UPLOAD_USER_AGENT


@pytest.mark.parametrize("provider", ["catbox", "imgbb", "freeimage"])
def test_upload_and_verification_requests_carry_the_bdencode_agent(
    tmp_path: Path, provider: str
) -> None:
    path = tmp_path / "proof.png"
    path.write_bytes(PNG)
    agents: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append((request.method, request.headers.get("user-agent", "")))
        if request.method == "POST":
            if provider == "catbox":
                return httpx.Response(200, text="https://files.catbox.moe/proof.png")
            image = "https://i.ibb.co/abc/proof.png" if provider == "imgbb" else "https://iili.io/proof.png"
            viewer = "https://ibb.co/abc" if provider == "imgbb" else "https://freeimage.host/i/proof"
            return httpx.Response(200, json={
                "status_code": 200, "success": True, "status": 200,
                "data": {"url": image, "url_viewer": viewer, "image": {"url": image}},
                "image": {"url": image, "url_viewer": viewer},
            })
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    if provider == "catbox":
        uploader = CatboxClient(client=client)
    elif provider == "imgbb":
        uploader = ImgBBClient(client=client, credential_loader=lambda *_args, **_kwargs: "key")
    else:
        uploader = FreeimageClient(client=client, credential_loader=lambda *_args, **_kwargs: "key")
    try:
        uploader.upload_png(path)
    except Exception:
        # The provider-specific response contracts are covered elsewhere;
        # here only the request headers matter.
        pass

    assert agents, "no request was sent"
    assert {method for method, _agent in agents} >= {"POST"}
    if provider == "catbox":
        # The verification download is the request files.catbox.moe refused.
        assert {method for method, _agent in agents} == {"POST", "GET"}
    assert all(agent == UPLOAD_USER_AGENT for _method, agent in agents)
