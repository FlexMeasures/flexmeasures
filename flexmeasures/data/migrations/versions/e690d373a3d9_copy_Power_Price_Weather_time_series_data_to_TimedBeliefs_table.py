"""Copy Power/Price/Weather time series data to TimedBeliefs table

Revision ID: e690d373a3d9
Revises: 830e72a8b218
Create Date: 2021-12-27 15:01:38.967237

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e690d373a3d9"
down_revision = "830e72a8b218"
branch_labels = None
depends_on = None


def upgrade():

    # Declare ORM table views
    t_power = sa.Table(
        "power",
        sa.MetaData(),
        sa.Column("sensor_id"),
        sa.Column("datetime"),
        sa.Column("horizon"),
        sa.Column("value"),
        sa.Column("data_source_id"),
    )
    t_price = sa.Table(
        "price",
        sa.MetaData(),
        sa.Column("sensor_id"),
        sa.Column("datetime"),
        sa.Column("horizon"),
        sa.Column("value"),
        sa.Column("data_source_id"),
    )
    t_weather = sa.Table(
        "weather",
        sa.MetaData(),
        sa.Column("sensor_id"),
        sa.Column("datetime"),
        sa.Column("horizon"),
        sa.Column("value"),
        sa.Column("data_source_id"),
    )
    t_timed_belief = sa.Table(
        "timed_belief",
        sa.MetaData(),
        sa.Column("sensor_id"),
        sa.Column("event_start"),
        sa.Column("belief_horizon"),
        sa.Column("event_value"),
        sa.Column("cumulative_probability"),
        sa.Column("source_id"),
    )

    # Use SQLAlchemy's connection and transaction to go through the data
    connection = op.get_bind()

    copy_time_series_data(
        connection,
        t_price,
        t_timed_belief,
    )
    copy_time_series_data(
        connection,
        t_power,
        t_timed_belief,
    )
    copy_time_series_data(
        connection,
        t_weather,
        t_timed_belief,
    )


def downgrade():
    pass


def copy_time_series_data(
    connection,
    t_old_data_model,
    t_timed_belief,
    batch_size: int = 100000,
):
    mapping = {
        "value": "event_value",
        "data_source_id": "source_id",
        "datetime": "event_start",
        "horizon": "belief_horizon",
        "sensor_id": "sensor_id",
    }

    # Get data from old data model
    results = connection.execute(
        sa.select([getattr(t_old_data_model.c, a) for a in mapping.keys()])
    ).fetchall()

    if len(results) > 0:
        print(
            f"- copying {len(results)} rows from the {t_old_data_model.name} table to the {t_timed_belief.name} table..."
        )

    # Copy in batches and report on progress
    for i in range(len(results) // batch_size + 1):
        if i > 0:
            print(f"  - done copying {i*batch_size} rows...")

        insert_values = []
        for values in results[i * batch_size : (i + 1) * batch_size]:
            d = {k: v for k, v in zip(mapping.values(), values)}
            d["cumulative_probability"] = 0.5
            insert_values.append(d)
        op.bulk_insert(t_timed_belief, insert_values)

    if len(results) > 0:
        print(f"  - finished copying {len(results)} rows...")
