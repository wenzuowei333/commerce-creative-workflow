from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401
from app.db import Base


def test_core_tables_are_declared():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    tables = set(inspect(engine).get_table_names())

    assert {
        "users",
        "products",
        "product_assets",
        "product_attributes",
        "analysis_versions",
        "prompt_plans",
        "prompt_versions",
        "templates",
        "generation_batches",
        "generation_directions",
        "generation_items",
        "image_assets",
        "image_revisions",
        "task_events",
        "usage_ledger",
        "download_bundles",
        "deleted_objects",
        "idempotency_records",
    }.issubset(tables)
