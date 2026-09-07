from fastapi.testclient import TestClient

from astra.server import create_app


def test_status_and_static_ui_work_before_models_are_ready():
    with TestClient(create_app(load_models=False), base_url="http://localhost:7860") as client:
        status = client.get("/api/status")
        assert status.status_code == 200
        assert status.json()["thinking"] is False
        assert status.json()["ready"] is False
        page = client.get("/")
        assert "Einfach aussprechen" in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert client.get("/static/app.js").status_code == 200


def test_other_websites_cannot_open_a_microphone_session():
    with TestClient(create_app(load_models=False), base_url="http://localhost:7860") as client:
        for origin in ["https://evil.example", "null", "http://localhost.evil.example:7860"]:
            response = client.post("/api/offer", headers={"Origin": origin}, json={})
            assert response.status_code == 403
        assert client.post("/api/offer", json={}).status_code == 403


def test_unready_returns_actionable_status_and_invalid_sdp_is_rejected():
    with TestClient(create_app(load_models=False), base_url="http://localhost:7860") as client:
        headers = {"Origin": "http://localhost:7860"}
        assert client.post("/api/offer", headers=headers, json={}).status_code == 422
        response = client.post(
            "/api/offer", headers=headers, json={"sdp": "a" * 20, "type": "offer"}
        )
        assert response.status_code == 503
        assert response.json()["detail"]


def test_voices_endpoint_lists_selectable_voices():
    with TestClient(create_app(load_models=False), base_url="http://localhost:7860") as client:
        response = client.get("/api/voices")
        assert response.status_code == 200
        body = response.json()
        assert body["default"] == "alba"
        names = {voice["name"] for voice in body["voices"]}
        assert "alba" in names
        assert all({"name", "display_name", "gender"} <= voice.keys() for voice in body["voices"])


def test_offer_rejects_unknown_voice():
    with TestClient(create_app(load_models=False), base_url="http://localhost:7860") as client:
        response = client.post(
            "/api/offer",
            headers={"Origin": "http://localhost:7860"},
            json={"sdp": "a" * 20, "type": "offer", "voice": "not-a-real-voice"},
        )
        assert response.status_code == 422


def test_media_endpoint_returns_404_for_unknown_image():
    with TestClient(create_app(load_models=False), base_url="http://localhost:7860") as client:
        response = client.get("/api/media/does-not-exist")
        assert response.status_code == 404


def test_upload_requires_an_active_session():
    with TestClient(create_app(load_models=False), base_url="http://localhost:7860") as client:
        response = client.post(
            "/api/upload",
            headers={"Origin": "http://localhost:7860"},
            data={"pc_id": "no-such-session"},
            files={"file": ("test.pdf", b"%PDF-1.1", "application/pdf")},
        )
        assert response.status_code == 404


def test_disconnect_is_idempotent_and_host_is_checked():
    with TestClient(create_app(load_models=False), base_url="http://localhost:7860") as client:
        response = client.post(
            "/api/disconnect",
            headers={"Origin": "http://localhost:7860"},
            json={"pc_id": "already-gone"},
        )
        assert response.json() == {"ok": True}
        assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 403
