"""create annotation table

Revision ID: 7f8b8920355f
Revises: c1d316c60985
Create Date: 2022-01-29 20:23:29.996133

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7f8b8920355f"
down_revision = "c1d316c60985"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "annotation",
        sa.Column(
            "id", sa.Integer(), nullable=False, autoincrement=True, primary_key=True
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("alert", "holiday", "label", name="annotation_type"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.id"]),
    )
    op.create_unique_constraint(
        op.f("annotation_name_key"),
        "annotation",
        ["name", "start", "source_id", "type"],
    )


def downgrade():
    op.drop_constraint(op.f("annotation_name_key"), "annotation", type_="unique")
    op.drop_table("annotation")
    op.execute("DROP TYPE annotation_type;")
