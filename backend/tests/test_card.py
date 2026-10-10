import io

from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.card import render_card


def test_card_is_1200x630_png_and_fits_long_roasts():
    for roast in ("short", "word " * 400):
        png = render_card(repo="acme/" + "x" * 80, score=27, roast=roast, site="prejudge.app")
        img = Image.open(io.BytesIO(png))
        assert img.format == "PNG" and img.size == (1200, 630)
    render_card(repo="acme/demo", score=None, roast="Still cooking", site="x", source="template")


def test_card_and_share_page_endpoints(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_URL", "https://api.example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://prejudge.example.com")
    with TestClient(main.app) as c:
        aid = c.get("/api/examples").json()[0]["id"]
        r = c.get(f"/api/audits/{aid}/card.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(r.content)).size == (1200, 630)
        page = c.get(f"/r/{aid}")
        assert page.status_code == 200
        body = page.text
        assert f'og:image" content="https://api.example.com/api/audits/{aid}/card.png"' in body
        assert 'twitter:card" content="summary_large_image"' in body
        assert f"https://prejudge.example.com/a/{aid}" in body
        assert c.get("/r/nope").status_code == 404 and c.get("/api/audits/nope/card.png").status_code == 404


def test_share_page_escapes_repo_text(monkeypatch):
    with TestClient(main.app) as c:
        aid = c.get("/api/examples").json()[0]["id"]
        evil = '"><script>alert(1)</script>'
        row = main.db.get(aid)
        row["result"]["verdict"]["roast"] = evil
        main.db.update(aid, result=row["result"])
        body = c.get(f"/r/{aid}").text
        assert "<script>alert(1)" not in body and "&lt;script&gt;" in body
