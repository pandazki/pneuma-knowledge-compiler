"""The optional console mount serves assets and client routes without hiding API errors."""

import httpx
import pytest

from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "index.html").write_text("<html>synthetic console</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/x.js").write_text("console.log('synthetic');", encoding="utf-8")
    # A colliding asset must never take over an API namespace, even for an unknown route.
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1/missing").write_text("not an API", encoding="utf-8")
    return tmp_path


async def test_static_files_and_spa_fallback(static_dir):
    app = create_app(Settings(_env_file=None), static_dir=static_dir)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for path in ("/", "/library/abc", "/v10/library", "/assets/missing.js"):
            response = await client.get(path)
            assert response.status_code == 200
            assert response.text == "<html>synthetic console</html>"
            assert response.headers["content-type"].startswith("text/html")
        asset = await client.get("/assets/x.js")
        assert asset.status_code == 200
        assert asset.text == "console.log('synthetic');"
        assert asset.headers["content-type"].split(";")[0] in (
            "text/javascript", "application/javascript"
        )
        assert (await client.post("/library/abc")).status_code == 405


async def test_api_routes_and_errors_keep_priority(static_dir):
    app = create_app(Settings(_env_file=None), static_dir=str(static_dir))

    @app.get("/home/status")
    def home_status():
        return {"status": "ready"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/healthz")).json()["status"] == "ok"
        assert (await client.get("/home/status")).json() == {"status": "ready"}
        assert (await client.get("/openapi.json")).json()["info"]["title"] == app.title
        for path in ("/v1", "/v1/missing", "/healthz/missing", "/docs/missing", "/home/missing"):
            response = await client.get(path)
            assert response.status_code == 404
            assert response.json() == {"detail": "Not Found"}


async def test_no_static_directory_preserves_api_only_behavior():
    app = create_app(Settings(_env_file=None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/healthz")).status_code == 200
        for path in ("/", "/library/abc", "/assets/x.js"):
            assert (await client.get(path)).json() == {"detail": "Not Found"}
