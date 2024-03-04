"""Remove obsolete tables

Revision ID: ad98460751d9
Revises: 5a9473a817cb
Create Date: 2023-11-30 10:31:46.125670

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError
import click


from flexmeasures.data.config import db

# revision identifiers, used by Alembic.
revision = "ad98460751d9"
down_revision = "5a9473a817cb"
branch_labels = None
depends_on = None


def upgrade():
    tables = [
        "price",
        "power",
        "market",
        "market_type",
        "weather",
        "asset",
        "weather_sensor",
    ]

    #  check for existing data
    tables_with_data = []
    inspect = sa.inspect(db.engine)
    for table in tables:
        try:
            if inspect.has_table(table):
                result = db.session.execute(
                    sa.text(f"SELECT 1 FROM {table};")
                ).scalar_one_or_none()
                if result:
                    tables_with_data.append(table)
            else:
                print(f"Table {table} not found, continuing...")
        except ProgrammingError as exception:
            print(exception)
    db.session.close()  # https://stackoverflow.com/a/26346280/13775459

    if tables_with_data:
        click.confirm(
            f"The following tables still have data and will be dropped by this upgrade: {tables_with_data}. Use `flexmeasures db-ops dump` to create a backup. Are you sure you want to upgrade the database?: ",
            abort=True,
        )

    # drop indexes
    with op.batch_alter_table("power", schema=None) as batch_op:
        batch_op.drop_index("power_datetime_idx", if_exists=True)
        batch_op.drop_index("power_sensor_id_idx", if_exists=True)

    with op.batch_alter_table("asset_type", schema=None) as batch_op:
        batch_op.drop_index("asset_type_can_curtail_idx", if_exists=True)
        batch_op.drop_index("asset_type_can_shift_idx", if_exists=True)

    with op.batch_alter_table("weather", schema=None) as batch_op:
        batch_op.drop_index("weather_datetime_idx", if_exists=True)
        batch_op.drop_index("weather_sensor_id_idx", if_exists=True)

    with op.batch_alter_table("price", schema=None) as batch_op:
        batch_op.drop_index("price_datetime_idx", if_exists=True)
        batch_op.drop_index("price_sensor_id_idx", if_exists=True)

    # drop tables
    for table in tables:
        if inspect.has_table(table):
            op.drop_table(table)


def downgrade():
    op.create_table(
        "power",
        sa.Column(
            "datetime",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("sensor_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column(
            "value",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "horizon", postgresql.INTERVAL(), autoincrement=False, nullable=False
        ),
        sa.Column("data_source_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_source.id"],
            name="power_data_source_data_sources_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["sensor_id"],
            ["sensor.id"],
            name="power_sensor_id_sensor_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "datetime", "sensor_id", "horizon", "data_source_id", name="power_pkey"
        ),
    )

    op.create_table(
        "asset_type",
        sa.Column("name", sa.VARCHAR(length=80), autoincrement=False, nullable=False),
        sa.Column("is_consumer", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column("is_producer", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column("can_curtail", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column("can_shift", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column(
            "daily_seasonality", sa.BOOLEAN(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "weekly_seasonality", sa.BOOLEAN(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "yearly_seasonality", sa.BOOLEAN(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "display_name",
            sa.VARCHAR(length=80),
            server_default=sa.text("''::character varying"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "hover_label", sa.VARCHAR(length=80), autoincrement=False, nullable=True
        ),
        sa.PrimaryKeyConstraint("name", name="asset_type_pkey"),
        sa.UniqueConstraint("display_name", name="asset_type_display_name_key"),
        postgresql_ignore_search_path=False,
    )

    op.create_table(
        "weather_sensor_type",
        sa.Column("name", sa.VARCHAR(length=80), autoincrement=False, nullable=False),
        sa.Column(
            "display_name",
            sa.VARCHAR(length=80),
            server_default=sa.text("''::character varying"),
            autoincrement=False,
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("name", name="weather_sensor_type_pkey"),
        sa.UniqueConstraint(
            "display_name", name="weather_sensor_type_display_name_key"
        ),
        postgresql_ignore_search_path=False,
    )
    op.create_table(
        "weather_sensor",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("name", sa.VARCHAR(length=80), autoincrement=False, nullable=True),
        sa.Column(
            "weather_sensor_type_name",
            sa.VARCHAR(length=80),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "latitude",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "longitude",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "unit",
            sa.VARCHAR(length=80),
            server_default=sa.text("''::character varying"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "display_name",
            sa.VARCHAR(length=80),
            server_default=sa.text("''::character varying"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "event_resolution",
            postgresql.INTERVAL(),
            server_default=sa.text("'00:00:00'::interval"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "knowledge_horizon_fnc",
            sa.VARCHAR(length=80),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "knowledge_horizon_par",
            postgresql.JSON(astext_type=sa.Text()),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "timezone", sa.VARCHAR(length=80), autoincrement=False, nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["id"], ["sensor.id"], name="weather_sensor_id_sensor_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["weather_sensor_type_name"],
            ["weather_sensor_type.name"],
            name="weather_sensor_weather_sensor_type_name_weather_sensor__1390",
        ),
        sa.PrimaryKeyConstraint("id", name="weather_sensor_pkey"),
        sa.UniqueConstraint("name", name="weather_sensor_name_key"),
        sa.UniqueConstraint(
            "weather_sensor_type_name",
            "latitude",
            "longitude",
            name="weather_sensor_type_name_latitude_longitude_key",
        ),
    )
    op.create_table(
        "weather",
        sa.Column("sensor_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column(
            "datetime",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "value",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "horizon", postgresql.INTERVAL(), autoincrement=False, nullable=False
        ),
        sa.Column("data_source_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_source.id"],
            name="weather_data_source_data_sources_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["sensor_id"], ["sensor.id"], name="weather_sensor_id_sensor_fkey"
        ),
        sa.PrimaryKeyConstraint(
            "datetime", "sensor_id", "horizon", "data_source_id", name="weather_pkey"
        ),
    )
    op.create_table(
        "market_type",
        sa.Column("name", sa.VARCHAR(length=80), autoincrement=False, nullable=False),
        sa.Column(
            "daily_seasonality", sa.BOOLEAN(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "weekly_seasonality", sa.BOOLEAN(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "yearly_seasonality", sa.BOOLEAN(), autoincrement=False, nullable=False
        ),
        sa.Column(
            "display_name",
            sa.VARCHAR(length=80),
            server_default=sa.text("''::character varying"),
            autoincrement=False,
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("name", name="market_type_pkey"),
        sa.UniqueConstraint("display_name", name="market_type_display_name_key"),
        postgresql_ignore_search_path=False,
    )
    op.create_table(
        "market",
        sa.Column(
            "id",
            sa.INTEGER(),
            server_default=sa.text("nextval('market_id_seq'::regclass)"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("name", sa.VARCHAR(length=80), autoincrement=False, nullable=True),
        sa.Column(
            "market_type_name",
            sa.VARCHAR(length=80),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "display_name",
            sa.VARCHAR(length=80),
            server_default=sa.text("''::character varying"),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "unit",
            sa.VARCHAR(length=80),
            server_default=sa.text("''::character varying"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "event_resolution",
            postgresql.INTERVAL(),
            server_default=sa.text("'00:00:00'::interval"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "knowledge_horizon_fnc",
            sa.VARCHAR(length=80),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "knowledge_horizon_par",
            postgresql.JSON(astext_type=sa.Text()),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "timezone", sa.VARCHAR(length=80), autoincrement=False, nullable=False
        ),
        sa.ForeignKeyConstraint(["id"], ["sensor.id"], name="market_id_sensor_fkey"),
        sa.ForeignKeyConstraint(
            ["market_type_name"],
            ["market_type.name"],
            name="market_market_type_name_market_type_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="market_pkey"),
        sa.UniqueConstraint("display_name", name="market_display_name_key"),
        sa.UniqueConstraint("name", name="market_name_key"),
        postgresql_ignore_search_path=False,
    )

    op.create_table(
        "price",
        sa.Column(
            "datetime",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("sensor_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column(
            "value",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "horizon", postgresql.INTERVAL(), autoincrement=False, nullable=False
        ),
        sa.Column("data_source_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_source.id"],
            name="price_data_source_data_sources_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["sensor_id"], ["sensor.id"], name="price_sensor_id_sensor_fkey"
        ),
        sa.PrimaryKeyConstraint(
            "datetime", "sensor_id", "horizon", "data_source_id", name="price_pkey"
        ),
    )

    op.create_table(
        "asset",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column(
            "asset_type_name",
            sa.VARCHAR(length=80),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("name", sa.VARCHAR(length=80), autoincrement=False, nullable=True),
        sa.Column(
            "display_name", sa.VARCHAR(length=80), autoincrement=False, nullable=True
        ),
        sa.Column(
            "capacity_in_mw",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "latitude",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "longitude",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("owner_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column(
            "min_soc_in_mwh",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "max_soc_in_mwh",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "soc_in_mwh",
            postgresql.DOUBLE_PRECISION(precision=53),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "soc_datetime",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column("soc_udi_event_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column(
            "unit",
            sa.VARCHAR(length=80),
            server_default=sa.text("''::character varying"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("market_id", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column(
            "event_resolution",
            postgresql.INTERVAL(),
            server_default=sa.text("'00:00:00'::interval"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "knowledge_horizon_fnc",
            sa.VARCHAR(length=80),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "knowledge_horizon_par",
            postgresql.JSON(astext_type=sa.Text()),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "timezone", sa.VARCHAR(length=80), autoincrement=False, nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["asset_type_name"],
            ["asset_type.name"],
            name="asset_asset_type_name_asset_type_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["id"], ["sensor.id"], name="asset_id_sensor_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["market_id"], ["market.id"], name="asset_market_id_market_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["fm_user.id"],
            name="asset_owner_id_bvp_users_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="asset_pkey"),
        sa.UniqueConstraint("display_name", name="asset_display_name_key"),
        sa.UniqueConstraint("name", name="asset_name_key"),
    )

    with op.batch_alter_table("power", schema=None) as batch_op:
        batch_op.create_index("power_sensor_id_idx", ["sensor_id"], unique=False)
        batch_op.create_index("power_datetime_idx", ["datetime"], unique=False)

    with op.batch_alter_table("asset_type", schema=None) as batch_op:
        batch_op.create_index("asset_type_can_shift_idx", ["can_shift"], unique=False)
        batch_op.create_index(
            "asset_type_can_curtail_idx", ["can_curtail"], unique=False
        )

    with op.batch_alter_table("weather", schema=None) as batch_op:
        batch_op.create_index("weather_sensor_id_idx", ["sensor_id"], unique=False)
        batch_op.create_index("weather_datetime_idx", ["datetime"], unique=False)

    with op.batch_alter_table("price", schema=None) as batch_op:
        batch_op.create_index("price_sensor_id_idx", ["sensor_id"], unique=False)
        batch_op.create_index("price_datetime_idx", ["datetime"], unique=False)
