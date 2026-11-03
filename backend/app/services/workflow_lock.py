"""Showcase consistency lock; serializes short mutations, never Provider calls."""
from sqlalchemy import text
from sqlalchemy.orm import Session


def workflow_lock(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(742028240004)"))
