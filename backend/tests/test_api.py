from __future__ import annotations

import json
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from knowledge_librarian.api import create_app


def make_pdf(text: str) -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text((72, 72), text)
    result = document.tobytes()
    document.close()
    return result


def test_health_library_sync_and_answer(settings) -> None:
    with TestClient(create_app(settings)) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["mode"] == "offline"
        assert len(health.headers["x-request-id"]) == 32
        assert health.headers["x-content-type-options"] == "nosniff"
        assert health.headers["referrer-policy"] == "no-referrer"
        assert health.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
        assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
        assert client.get("/readyz").json()["status"] == "ready"

        sources = client.get("/api/v1/sources").json()
        demo_source = next(item for item in sources if item["source"] == "demo")
        assert demo_source["document_count"] == 5
        assert demo_source["last_synced_at"] is not None
        assert len(client.get("/api/v1/documents").json()) == 5

        answer = client.post(
            "/api/v1/chat/answer", json={"message": "What is the daily meal allowance?"}
        )
        assert answer.status_code == 200
        assert answer.json()["grounded"] is True
        assert answer.json()["citations"][0]["title"] == "Travel and Expenses"

        sync = client.post("/api/v1/sources/demo/sync")
        assert sync.status_code == 200
        assert sync.json()["unchanged"] == 5
        assert client.get(f"/api/v1/sync-jobs/{sync.json()['id']}").status_code == 200
        assert len(client.get("/api/v1/sync-jobs").json()) >= 2
        assert client.get("/api/v1/sync-jobs/missing").status_code == 404


def test_chat_sse_has_typed_grounded_events(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/chat",
            json={"message": "How soon is a severity-one alert acknowledged?"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "no-store" in response.headers["cache-control"]
        frames = [frame for frame in response.text.split("\n\n") if frame]
        event_types = [frame.splitlines()[0] for frame in frames]
        assert event_types[:2] == ["event: status", "event: status"]
        assert "event: citation" in event_types
        assert event_types[-1] == "event: done"
        citation_frame = next(frame for frame in frames if frame.startswith("event: citation"))
        citation_data = json.loads(citation_frame.splitlines()[1].removeprefix("data: "))
        assert citation_data["title"] == "Customer Incident Playbook"
        done_data = json.loads(frames[-1].splitlines()[1].removeprefix("data: "))
        assert done_data["grounded"] is True


def test_pdf_upload_validation_and_indexing(settings) -> None:
    with TestClient(create_app(settings)) as client:
        invalid = client.post(
            "/api/v1/sources/local-pdf",
            files={"file": ("../unsafe.pdf", b"not-pdf", "application/pdf")},
        )
        assert invalid.status_code == 422

        valid = client.post(
            "/api/v1/sources/local-pdf",
            files={
                "file": (
                    "benefits.pdf",
                    make_pdf("The synthetic wellness allowance is 500 dollars annually."),
                    "application/pdf",
                )
            },
        )
        assert valid.status_code == 201
        assert valid.json()["job"]["created"] == 1
        documents = client.get("/api/v1/documents").json()
        assert any(item["source"] == "local_pdf" for item in documents)


def test_disabled_source_and_request_validation_are_sanitized(settings) -> None:
    with TestClient(create_app(settings)) as client:
        disabled = client.post("/api/v1/sources/clickup/sync")
        assert disabled.status_code == 409
        assert "disabled" in disabled.json()["detail"]
        invalid = client.post("/api/v1/chat/answer", json={"message": " "})
        assert invalid.status_code == 422


def test_configured_container_static_ui_is_served_after_api_routes(
    settings, tmp_path: Path
) -> None:
    # Simulate a non-editable install: Python lives under .venv while the web build is copied
    # separately to /app/frontend/dist. Serving must depend on settings, never package __file__.
    static = tmp_path / "app" / "frontend" / "dist"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<h1>Container UI</h1>", encoding="utf-8")
    configured = settings.model_copy(update={"frontend_dist": static})
    with TestClient(create_app(configured)) as client:
        assert "Container UI" in client.get("/").text
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.get("/api/v1/documents").status_code == 200
