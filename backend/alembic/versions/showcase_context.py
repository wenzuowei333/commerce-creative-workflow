"""Link showcase plans to the explicitly confirmed analysis version."""
from alembic import op
import sqlalchemy as sa
revision = "showcase_context"
down_revision = "showcase_workflow"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("prompt_plans") as batch:
        batch.add_column(sa.Column("analysis_version_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_analysis_version_id_prompt_plans_analysis_versions", "analysis_versions", ["analysis_version_id"], ["id"])


def downgrade():
    with op.batch_alter_table("prompt_plans") as batch:
        batch.drop_constraint("fk_analysis_version_id_prompt_plans_analysis_versions", type_="foreignkey")
        batch.drop_column("analysis_version_id")
