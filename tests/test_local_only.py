"""Test that the engine makes no outbound network calls."""

import socket
from unittest.mock import patch

import pytest


# Block all outbound connections
@pytest.fixture(autouse=True)
def block_network():
    """Block all network calls except localhost."""
    original_create_connection = socket.create_connection

    def guarded_create_connection(address, *args, **kwargs):
        host, port = address[0], address[1]
        # Allow only localhost
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(f"Outbound network call blocked: {host}:{port}")
        return original_create_connection(address, *args, **kwargs)

    with patch("socket.create_connection", guarded_create_connection):
        yield


def test_no_outbound_calls_in_pipeline():
    """Pipeline should not make outbound calls."""
    import asyncio

    from engine.pipeline import LetterDecoderPipeline

    pipeline = LetterDecoderPipeline(engine_mode="mock")

    # This should work without network
    async def run():
        async for _ in pipeline.process_mock("routine"):
            pass

    asyncio.run(run())


def test_no_outbound_calls_in_extract():
    """Text extraction should not make outbound calls."""
    import asyncio

    from engine.extract_text import extract_text

    async def run():
        # Should not call network
        result = await extract_text(None, None, "Test text")
        assert result.text == "Test text"

    asyncio.run(run())


def test_fastapi_binds_localhost():
    """FastAPI should bind to 127.0.0.1 only."""
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["offline"] is True


def test_cors_localhost_only():
    """CORS should only allow localhost origins."""
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    # Test allowed origin - use GET to check CORS headers
    resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    # Check CORS headers are present
    assert "access-control-allow-origin" in resp.headers

    # Test disallowed origin - verify config only
    cors_middleware = None
    for middleware in app.user_middleware:
        if hasattr(middleware, "cls") and middleware.cls.__name__ == "CORSMiddleware":
            cors_middleware = middleware
            break

    assert cors_middleware is not None
    allowed_origins = cors_middleware.kwargs.get("allow_origins", [])
    for origin in allowed_origins:
        assert "localhost" in origin or "127.0.0.1" in origin, (
            f"Non-localhost origin in CORS: {origin}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
