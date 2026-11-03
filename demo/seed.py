"""New synthetic fixtures. No workflow confirmations or successful tasks are fabricated."""
import argparse
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app import models as m
from app.config import Settings
from app.demo_safety import ensure_demo_database
from app.providers import MockAIProvider
from app.security import hash_password

ROOT = Path(__file__).resolve().parents[1]
BASE_TIME = datetime(2026, 10, 1, tzinfo=UTC)
PASSWORD = "LocalDemo-2026!"
PRODUCTS = [
    {"name":"虚构青绿随行杯", "sku":"DEMO-CUP-001", "brand":"DEMO LAB", "kind":"cup"},
    {"name":"虚构桌面收纳盒", "sku":"DEMO-BOX-001", "brand":"DEMO LAB", "kind":"box"},
]


def stable_id(key):
    return str(uuid5(NAMESPACE_URL, "urn:portfolio-demo:" + key))


def reference_png(kind, angle):
    # Authored geometric test illustrations: not a photograph or AI generation.
    canvas = Image.new("RGB", (640, 640), (240, 246, 244))
    draw = ImageDraw.Draw(canvas)
    offset = angle * 5
    if kind == "cup":
        draw.rounded_rectangle((205+offset,145,405+offset,480), radius=35, fill=(49,154,143))
        draw.rounded_rectangle((390+offset,205,470+offset,365), radius=30, outline=(49,154,143), width=20)
        draw.ellipse((205+offset,130,405+offset,185), fill=(30,105,101))
    else:
        draw.rounded_rectangle((150+offset,220,490+offset,470), radius=25, fill=(49,154,143))
        draw.rounded_rectangle((140+offset,200,500+offset,250), radius=15, fill=(30,105,101))
        draw.rounded_rectangle((255+offset,300,385+offset,345), radius=8, fill=(235,247,242))
    draw.text((30,30), "SYNTHETIC DEMO REFERENCE", fill=(20,70,67))
    draw.text((30,590), f"DEMO {kind.upper()} / VIEW {angle+1} / NOT A PHOTO", fill=(20,70,67))
    out = BytesIO()
    canvas.save(out, format="PNG", optimize=False)
    return out.getvalue()


def export_assets():
    fixtures = ROOT / "demo/fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    assets = []
    for product in PRODUCTS:
        for angle in range(4):
            key = f"references/{product['sku'].lower()}-{angle+1}.png"
            content = reference_png(product["kind"], angle)
            p = fixtures / key
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            assets.append({"path":key,"sku":product["sku"],"position":angle,"size_bytes":len(content),
                           "sha256":hashlib.sha256(content).hexdigest(), "origin":"authored_geometric_test_fixture",
                           "rights":"Created for this showcase; reusable with this demo",
                           "is_mock_output":False,"is_real_product":False,"width":640,"height":640})
    provider = MockAIProvider()
    for i in range(5):
        content = provider.generate_image(prompt=f"DEMO mock sample {i+1}", images=[], size="1024x1024", quality="medium", output_format="png")
        key = f"mock-outputs/sample-{i+1}.png"
        p = fixtures / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        assets.append({"path":key,"size_bytes":len(content),"sha256":hashlib.sha256(content).hexdigest(),
                       "origin":"existing_MockAIProvider", "rights":"Procedural preview output; no external input",
                       "is_mock_output":True,"is_real_product":False,"width":1024,"height":1024})
    (fixtures / "assets-manifest.json").write_text(json.dumps({"synthetic":True,"base_date":"2026-10-01","assets":assets}, ensure_ascii=False, indent=2)+"\n")
    (fixtures / "products.json").write_text(json.dumps({"synthetic":True,"products":PRODUCTS}, ensure_ascii=False, indent=2)+"\n")
    (fixtures / "expected.json").write_text(json.dumps({"products":2,"reference_assets":8,"mock_sample_files":5,
        "owner":"demo_admin","other_user":"demo_other","generation_batches":0,"generation_items":0,
        "note":"五张Mock样例仅为磁盘素材，没有预置成已执行批次；完整流程在阶段四运行。"}, ensure_ascii=False, indent=2)+"\n")
    return assets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    assets = export_assets()
    if args.export_only:
        print(json.dumps({"products":2,"references":8,"mock_samples":5,"exported":True}))
        return
    settings = Settings()
    ensure_demo_database(settings.database_url, "creative_demo", ROOT)
    if settings.environment != "demo" or settings.ai_mode != "mock" or settings.media_backend != "local":
        raise SystemExit("Seed only supports the isolated default demo configuration")
    engine = create_engine(settings.database_url)
    media = Path(settings.media_root)
    with Session(engine) as db, db.begin():
        if db.scalar(select(func.count()).select_from(m.AnalysisVersion)):
            print(json.dumps({"synthetic": True, "existing_workflow_preserved": True}))
            return
        for username in ("demo_admin", "demo_other"):
            row_id = stable_id(username)
            existing = db.get(m.User, row_id)
            upsert(db, m.User, row_id, username=username,
                   password_hash=existing.password_hash if existing else hash_password(PASSWORD),
                   is_active=True, created_at=BASE_TIME, updated_at=BASE_TIME)
        for product in PRODUCTS:
            product_id = stable_id(product["sku"])
            upsert(db, m.Product, product_id, owner_id=stable_id("demo_admin"), name=product["name"],
                   sku=product["sku"], brand=product["brand"], status="draft", profile_json={},
                   created_at=BASE_TIME, updated_at=BASE_TIME)
            for asset in [a for a in assets if a.get("sku") == product["sku"]]:
                row_id = stable_id(asset["path"])
                content = (ROOT / "demo/fixtures" / asset["path"]).read_bytes()
                object_key = f"demo/{product_id}/{row_id}.png"
                thumbnail_key = f"demo/{product_id}/{row_id}-thumbnail.png"
                for key in (object_key, thumbnail_key):
                    target = media / key
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                upsert(db, m.ProductAsset, row_id, product_id=product_id, object_key=object_key,
                       thumbnail_object_key=thumbnail_key, original_name=Path(asset["path"]).name,
                       content_type="image/png", size_bytes=len(content), sha256=asset["sha256"],
                       width=640, height=640, position=asset["position"], is_primary=asset["position"]==0,
                       angle=["front","side","back","detail"][asset["position"]], status="ready",
                       created_at=BASE_TIME, updated_at=BASE_TIME)
    print(json.dumps({"synthetic":True,"products":2,"ready_reference_assets":8,"idempotent":True}))


def upsert(db, model, row_id, **fields):
    row = db.get(model, row_id)
    if row is None:
        row = model(id=row_id)
        db.add(row)
    for key,value in fields.items():
        setattr(row,key,value)
    db.flush()
    return row


if __name__ == "__main__":
    main()
