"""Verify synthetic inputs and assets; does not execute generation batches."""
import hashlib
import json
from io import BytesIO
from pathlib import Path
from PIL import Image
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, configure_mappers
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from app import models as m
from app.config import Settings
from app.db import Base
from app.security import verify_password

ROOT = Path(__file__).resolve().parents[1]


def main():
    settings = Settings()
    engine = create_engine(settings.database_url)
    configure_mappers()
    with engine.connect() as conn:
        drift = compare_metadata(MigrationContext.configure(conn, opts={'compare_type':True}), Base.metadata)
        assert not drift, repr(drift)
    manifest = json.loads((ROOT/'demo/fixtures/assets-manifest.json').read_text())
    assert len(manifest['assets']) == 13
    for asset in manifest['assets']:
        data = (ROOT/'demo/fixtures'/asset['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == asset['sha256']
        with Image.open(BytesIO(data)) as im:
            assert im.size == (asset['width'],asset['height'])
            assert not im.getexif() and not im.info
    with Session(engine) as db:
        for table, expected in [(m.User,2),(m.Product,2),(m.ProductAsset,8)]:
            assert db.scalar(select(func.count()).select_from(table)) == expected
        for user in db.scalars(select(m.User)):
            assert verify_password(user.password_hash,'LocalDemo-2026!')
        for asset in db.scalars(select(m.ProductAsset)):
            assert asset.status == 'ready'
            data = (Path(settings.media_root)/asset.object_key).read_bytes()
            assert hashlib.sha256(data).hexdigest() == asset.sha256
        normalized = {}
        for table in Base.metadata.sorted_tables:
            rows = [dict(r) for r in db.execute(select(table).order_by(table.c.id)).mappings()]
            for row in rows:
                row.pop('password_hash',None)
            normalized[table.name]=rows
        digest = hashlib.sha256(json.dumps(normalized,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
    print(json.dumps({'status':'passed','scope':'schema_and_synthetic_inputs_runtime_allowed','tables':18,
                      'products':2,'reference_assets':8,'mock_sample_files':5,
                      'normalized_data_sha256':digest}))


if __name__=='__main__':
    main()
