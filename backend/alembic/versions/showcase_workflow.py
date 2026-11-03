"""Add explicit demo scenario and immutable generation settings snapshot."""
from alembic import op
import sqlalchemy as sa

revision = "showcase_workflow"
down_revision = "dc09848397a8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generation_batches", sa.Column("demo_scenario", sa.String(30), nullable=False, server_default="success"))
    op.add_column("generation_batches", sa.Column("plan_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("generation_batches", sa.Column("plan_snapshot_json", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("generation_batches", "plan_snapshot_json")
    op.drop_column("generation_batches", "plan_version")
    op.drop_column("generation_batches", "demo_scenario")
