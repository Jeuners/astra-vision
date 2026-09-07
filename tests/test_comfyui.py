import httpx
import pytest

from astra.comfyui import ComfyUIError, generate_image


def _patched_client(monkeypatch, handler):
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_generate_image_returns_bytes_from_completed_job(monkeypatch):
    png_bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "abc123"})
        if request.url.path == "/history/abc123":
            return httpx.Response(
                200,
                json={
                    "abc123": {
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": "out.png", "subfolder": "", "type": "output"}
                                ]
                            }
                        }
                    }
                },
            )
        if request.url.path == "/view":
            return httpx.Response(200, content=png_bytes)
        raise AssertionError(f"unexpected request: {request.url}")

    _patched_client(monkeypatch, handler)
    result = await generate_image("http://fake-comfyui", "a cat")
    assert result == png_bytes


@pytest.mark.asyncio
async def test_generate_image_raises_when_comfyui_unreachable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patched_client(monkeypatch, handler)
    with pytest.raises(ComfyUIError):
        await generate_image("http://fake-comfyui", "a cat")


@pytest.mark.asyncio
async def test_generate_image_times_out_if_job_never_completes(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "abc123"})
        if request.url.path == "/history/abc123":
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected request: {request.url}")

    _patched_client(monkeypatch, handler)
    with pytest.raises(ComfyUIError, match="Zeitüberschreitung"):
        await generate_image("http://fake-comfyui", "a cat", timeout=0.2)
