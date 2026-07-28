import httpx

from pneuma_knowledge_service import __version__
from pneuma_knowledge_service.api.app import create_app


async def test_healthz_ok():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}
