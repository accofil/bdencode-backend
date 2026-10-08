"""Shared test set-up."""

from __future__ import annotations

import pytest

import bdencode.worker as worker_module


@pytest.fixture(autouse=True)
def _no_upload_retry_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upload failures surface at once unless a test sets its own retry delays."""

    monkeypatch.setattr(worker_module, "UPLOAD_RETRY_DELAYS", ())
