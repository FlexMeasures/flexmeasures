"""Make DataSource a subclass of timely-beliefs BeliefSource
The "label" column is renamed to "name" and becomes mandatory. It should typically define a person's or organisation's name.
Existing labels are renamed and a few new data source types are set, namely "crawling script" and "demo script".
We still have a few names containing additional information, namely which versioned model was used by forecasting scripts.

Revision ID: 3db3e71d101d
Revises: 7987667dbd43
Create Date: 2020-08-10 15:31:28.391337

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "3db3e71d101d"
down_revision = "7987667dbd43"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("data_sources", "label", new_column_name="name", nullable=False)
    op.execute(
        """
        update data_sources set type = 'crawling script' where name = 'data retrieved from KEPCO';
        update data_sources set name = 'KEPCO' where name = 'data retrieved from KEPCO';
        update data_sources set type = 'demo script' where name = 'data entered for demonstration purposes';
        update data_sources set name = 'Seita' where name = 'data entered for demonstration purposes';
        update data_sources set type = 'scheduling script' where name ~ '^schedule by Seita' and type = 'script';
        update data_sources set name = 'Seita' where name = 'schedule by Seita' and type = 'scheduling script';
        update data_sources set name = 'Seita (generic model_a v3)' where name = 'forecast by Seita (generic model_a (v3))' and type = 'forecasting script';
        update data_sources set name = 'Seita (generic model_a v2)' where name = 'forecast by Seita (generic model_a (v2))' and type = 'forecasting script';
        update data_sources set name = 'Seita (generic model_a v1)' where name = 'forecast by Seita (generic model_a (v1))' and type = 'forecasting script';
        update data_sources set name = 'Seita (linear-OLS model v2)' where name = 'forecast by Seita (linear-OLS model (v2))' and type = 'forecasting script';
        update data_sources set type = 'forecasting script' where name ~ '^forecast by Seita' and type = 'script';
        update data_sources set name = 'Seita (naive model v1)' where name = 'forecast by Seita (naive model (v1))' and type = 'forecasting script';
        update data_sources set name = 'DarkSky' where name = 'forecast by DarkSky for the Jeju region' and type = 'forecasting script';
        update data_sources set name = bvp_users.username from bvp_users where data_sources.user_id = bvp_users.id;
        """
    )


def downgrade():
    op.execute(
        """
        update data_sources set name = concat('data entered by user ', bvp_users.username) from bvp_users where data_sources.user_id = bvp_users.id;
        update data_sources set name = 'forecast by DarkSky for the Jeju region' where name = 'DarkSky' and type = 'forecasting script';
        update data_sources set name = 'forecast by Seita (naive model (v1))' where name = 'Seita (naive model v1)' and type = 'forecasting script';
        update data_sources set name = 'forecast by Seita (linear-OLS model (v2))' where name = 'Seita (linear-OLS model v2)' and type = 'forecasting script';
        update data_sources set name = 'forecast by Seita (generic model_a (v1))' where name = 'Seita (generic model_a v1)' and type = 'forecasting script';
        update data_sources set name = 'forecast by Seita (generic model_a (v2))' where name = 'Seita (generic model_a v2)' and type = 'forecasting script';
        update data_sources set name = 'forecast by Seita (generic model_a (v3))' where name = 'Seita (generic model_a v3)' and type = 'forecasting script';
        update data_sources set name = 'schedule by Seita' where name = 'Seita' and type = 'scheduling script';
        update data_sources set name = 'data entered for demonstration purposes' where name = 'Seita' and type = 'demo script';
        update data_sources set type = 'script' where name = 'data entered for demonstration purposes';
        update data_sources set name = 'data retrieved from KEPCO' where name = 'KEPCO';
        update data_sources set type = 'script' where name = 'data retrieved from KEPCO';
        """
    )
    op.alter_column("data_sources", "name", new_column_name="label", nullable=True)
