"""Real PostgreSQL/Redis integration fixtures, separate from source SQLite tests."""
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "postgresql+psycopg://portfolio_demo:local-demo-only@127.0.0.1:25437/creative_demo"
REDIS = "redis://127.0.0.1:26381/0"
os.environ.update(ENVIRONMENT="demo", DATABASE_URL=DATABASE, REDIS_URL=REDIS,
    MEDIA_ROOT=str(ROOT / "runtime/media"), QUEUE_MODE="dramatiq", SESSION_BACKEND="redis",
    AI_MODE="mock", GENERATION_LEASE_SECONDS="1.5", GENERATION_HEARTBEAT_SECONDS="0.2",
    DEMO_GENERATION_DELAY_SECONDS="0.05", PYTHONDONTWRITEBYTECODE="1")

from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text, select
from app.config import Settings, get_settings
from app.main import create_app
from app.db import Base
from app import models
from app.security import hash_password
from demo.seed import stable_id, PRODUCTS


@pytest.fixture(scope="session", autouse=True)
def migrated():
    if os.environ.get("SHOWCASE_PG_CHECKS") != "1":
        pytest.skip("Use demo/run_checks.py to authorize the dedicated disposable test services")
    subprocess.run([os.sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
                   cwd=ROOT, check=True, capture_output=True)
    return hash_password("LocalDemo-2026!")


@pytest.fixture
def ctx(migrated):
    get_settings.cache_clear()
    settings = Settings()
    assert settings.database_url == DATABASE and settings.redis_url == REDIS
    app = create_app(settings)
    factory = app.state.session_factory
    with factory() as db:
        assert db.get_bind().dialect.name == "postgresql"
        names = ', '.join('"' + table.name + '"' for table in Base.metadata.sorted_tables)
        db.execute(text("TRUNCATE " + names + " CASCADE"))
        db.commit()
        for username in ("demo_admin", "demo_other"):
            db.add(models.User(id=stable_id(username), username=username, password_hash=migrated, is_active=True))
        db.flush()
        for product in PRODUCTS:
            product_id = stable_id(product["sku"])
            db.add(models.Product(id=product_id, owner_id=stable_id("demo_admin"), name=product["name"],
                sku=product["sku"], brand=product["brand"], status="draft", profile_json={}))
            db.flush()
            for position in range(4):
                asset_id = stable_id(f"{product['sku']}-test-{position}")
                fixture = ROOT / f"demo/fixtures/references/{product['sku'].lower()}-{position+1}.png"
                key = f"tests/{asset_id}.png"
                app.state.media_store.put_bytes(key, fixture.read_bytes(), "image/png")
                db.add(models.ProductAsset(id=asset_id, product_id=product_id, object_key=key,
                    thumbnail_object_key=key, original_name=fixture.name, content_type="image/png",
                    size_bytes=fixture.stat().st_size, sha256="demo", width=640, height=640,
                    position=position, is_primary=position==0, angle="front", status="ready"))
        db.commit()
    Redis.from_url(REDIS).flushdb()
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username":"demo_admin", "password":"LocalDemo-2026!"})
        assert login.status_code == 200
        yield SimpleNamespace(client=client, settings=settings, factory=factory,
            csrf=login.json()["data"]["csrf_token"], product_id=stable_id("DEMO-CUP-001"))
    factory.kw["bind"].dispose()


def headers(ctx, key=None):
    return {"X-CSRF-Token":ctx.csrf, "Idempotency-Key":key or str(uuid4())}


def prepare(ctx, count=5, kind="main"):
    r=ctx.client.post(f"/api/v1/products/{ctx.product_id}/analysis",headers=headers(ctx));assert r.status_code==201,r.text
    analysis=r.json()["data"]
    for a in analysis["result"]["attributes"]: a["user_confirmed"]=True
    r=ctx.client.post(f"/api/v1/analysis/{analysis['id']}/confirm",headers=headers(ctx),json={"profile":analysis["result"]["profile"],"attributes":analysis["result"]["attributes"]});assert r.status_code==200,r.text
    r=ctx.client.post("/api/v1/prompt-plans",headers=headers(ctx),json={"product_id":ctx.product_id,"generation_type":kind,"image_count":count});assert r.status_code==201,r.text
    plan=r.json()["data"]
    r=ctx.client.post(f"/api/v1/prompt-plans/{plan['id']}/confirm",headers=headers(ctx),json={"plan":plan["plan"]});assert r.status_code==200,r.text
    return r.json()["data"]


def start(ctx, plan, scenario="success", key=None):
    r=ctx.client.post("/api/v1/generation-batches",headers=headers(ctx,key),json={"prompt_plan_id":plan["id"],"demo_scenario":scenario})
    assert r.status_code==201,r.text
    return r.json()["data"]
