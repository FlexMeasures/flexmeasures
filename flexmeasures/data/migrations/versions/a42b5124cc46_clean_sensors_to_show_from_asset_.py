"""Remove sensors_to_show key from attributes column

Revision ID: 2ba59c7c954e
Revises: 950e23e3aa54
Create Date: 2024-12-10 09:31:06.603743

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2ba59c7c954e"
down_revision = "950e23e3aa54"
branch_labels = None
depends_on = None


def upgrade():
    # Fetch all rows in the generic_assets table, update 'attributes' column by removing the 'sensors_to_show' key
    connection = op.get_bind()
    table_name = "generic_asset"
    attribute_key_to_remove = "sensors_to_show"

    # Use raw SQL to fetch and update rows
    connection.execute(
        sa.text(
            f"""
        UPDATE {table_name}
        SET attributes = attributes::jsonb - '{attribute_key_to_remove}'
        WHERE attributes IS NOT NULL;
        """
        )
    )


def downgrade():
    # This downgrade should be done together with the downgrade of the 950e23e3aa54 revision, which restores the sensors_to_show attribute.
    pass
