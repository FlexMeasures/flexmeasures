"""squash baseline: the whole schema as of legacy revision c7a2f13b9e04

This is the root of the current revision tree.
It builds, in one step, the schema that the 120 revisions of the frozen legacy tree
(``versions_legacy/``, root ``01fe99da5716``, head ``c7a2f13b9e04``) build in 120 steps.
A fresh install runs only this revision; the legacy files are never imported or executed.

An existing database does not run it.
``flexmeasures db upgrade`` walks such a database through the legacy tree to ``c7a2f13b9e04``,
and then *stamps* this revision without running it, because at that point the schema it would have built is already there.
See ``flexmeasures.data.utils.upgrade_database_schema`` for that orchestration.

What the schema holds, in dependency order:

- Tenancy and access: ``plan``, ``account``, ``account_role``, ``roles_accounts``, ``fm_user``, ``role``, ``roles_users``.
  Accounts can nest through ``consultancy_account_id``, and carry branding, ``attributes`` and ``secrets``.
- The asset tree: ``generic_asset_type``, ``generic_asset``.
  Assets nest through ``parent_asset_id``, guarded by a self-reference check constraint,
  and name uniqueness is enforced by three partial indexes, one each for child assets, public roots and account roots.
- Measurement: ``sensor``, ``data_source``, ``timed_belief``.
  ``timed_belief`` is the largest table, keyed by sensor, source, event start, belief horizon and cumulative probability.
- The ``sensor_data_source`` summary of which sources have recorded for which sensors,
  kept current by a statement-level trigger on ``timed_belief`` (installed at the end of ``upgrade()``).
- Annotations: ``annotation`` plus its three link tables for accounts, assets and sensors.
- Automations: ``automation``, scheduling generators against assets.
- Bookkeeping: ``audit_log``, ``asset_audit_log``, ``latest_task_run``.

Two enum types are created along with the tables that use them: ``annotation_type`` and ``ratelimitkey``.
The ``cube`` and ``earthdistance`` extensions are expected to exist already; no revision has ever created them.

Revision ID: 812621895c9c
Revises:
Create Date: 2026-09-15T10:00:00

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from flexmeasures.data.models.time_series import (
    RECORD_SENSOR_DATA_SOURCES_FUNCTION,
    RECORD_SENSOR_DATA_SOURCES_TRIGGER,
)

# revision identifiers, used by Alembic.
revision = "812621895c9c"
down_revision = None
branch_labels = None
depends_on = None

DOWNGRADE_MESSAGE = (
    "Cannot downgrade past the squash baseline (812621895c9c). "
    "This revision replaces the 120 legacy revisions up to c7a2f13b9e04, "
    "and there is no honest step from it back into that chain. "
    "To go back further than this, restore a backup. See https://flexmeasures.readthedocs.io/latest/host/data.html."
)


def upgrade():
    op.create_table(
        "account_role",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.VARCHAR(length=80), nullable=True),
        sa.Column("description", sa.VARCHAR(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="account_role_pkey"),
        sa.UniqueConstraint("name", name="account_role_name_key"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_datetime", postgresql.TIMESTAMP(), nullable=True),
        sa.Column("event", sa.VARCHAR(length=500), nullable=True),
        sa.Column("active_user_id", sa.INTEGER(), nullable=True),
        sa.Column("active_user_name", sa.VARCHAR(length=255), nullable=True),
        sa.Column("affected_user_id", sa.INTEGER(), nullable=True),
        sa.Column("affected_account_id", sa.INTEGER(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="audit_log_pkey"),
    )
    op.create_table(
        "data_source",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.VARCHAR(length=120), nullable=False),
        sa.Column("type", sa.VARCHAR(length=80), nullable=True),
        sa.Column("user_id", sa.INTEGER(), nullable=True),
        sa.Column("model", sa.VARCHAR(length=80), nullable=True),
        sa.Column("version", sa.VARCHAR(length=17), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column("attributes_hash", postgresql.BYTEA(), nullable=True),
        sa.Column("account_id", sa.INTEGER(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="data_sources_pkey"),
        sa.UniqueConstraint(
            "name",
            "user_id",
            "account_id",
            "model",
            "version",
            "attributes_hash",
            name="data_source_name_key",
        ),
        sa.UniqueConstraint("user_id", name="data_source_user_id_key"),
    )
    op.create_table(
        "generic_asset_type",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.VARCHAR(length=80), nullable=True),
        sa.Column("description", sa.VARCHAR(length=80), nullable=True),
        sa.PrimaryKeyConstraint("id", name="generic_asset_type_pkey"),
        sa.UniqueConstraint("name", name="generic_asset_type_name_key"),
    )
    op.create_table(
        "latest_task_run",
        sa.Column("name", sa.VARCHAR(length=80), nullable=False),
        sa.Column("datetime", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.BOOLEAN(), nullable=True),
        sa.PrimaryKeyConstraint("name", name="latest_task_run_pkey"),
    )
    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.VARCHAR(length=80), nullable=False),
        sa.Column("default_rate_limit", sa.VARCHAR(length=80), nullable=True),
        sa.Column("trigger_rate_limit", sa.VARCHAR(length=80), nullable=True),
        sa.Column(
            "rate_limit_key",
            postgresql.ENUM(
                "ACCOUNT_PLUS_ASSET", "ACCOUNT", "USER", name="ratelimitkey"
            ),
            nullable=True,
        ),
        sa.Column("max_users", sa.INTEGER(), nullable=True),
        sa.Column("max_assets", sa.INTEGER(), nullable=True),
        sa.Column("max_clients", sa.INTEGER(), nullable=True),
        sa.Column(
            "legacy", sa.BOOLEAN(), server_default=sa.text("false"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="plan_pkey"),
        sa.UniqueConstraint("name", name="plan_name_key"),
    )
    op.create_table(
        "role",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.VARCHAR(length=80), nullable=True),
        sa.Column("description", sa.VARCHAR(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="role_pkey"),
        sa.UniqueConstraint("name", name="role_name_key"),
    )
    op.create_table(
        "account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.VARCHAR(length=100), nullable=True),
        sa.Column("consultancy_account_id", sa.INTEGER(), nullable=True),
        sa.Column("primary_color", sa.VARCHAR(length=7), nullable=True),
        sa.Column("secondary_color", sa.VARCHAR(length=7), nullable=True),
        sa.Column("logo_url", sa.VARCHAR(length=255), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "secrets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("plan_id", sa.INTEGER(), nullable=True),
        sa.ForeignKeyConstraint(
            ["consultancy_account_id"],
            ["account.id"],
            name="account_consultancy_account_id_account_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plan.id"], name="account_plan_id_plan_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="account_pkey"),
        sa.UniqueConstraint("name", name="account_name_key"),
    )
    op.create_table(
        "annotation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("start", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("belief_time", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("source_id", sa.INTEGER(), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(
                "alert",
                "holiday",
                "label",
                "feedback",
                "warning",
                "error",
                name="annotation_type",
            ),
            nullable=False,
        ),
        sa.Column("content", sa.VARCHAR(length=1024), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_source.id"],
            name="annotation_source_id_data_source_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="annotation_pkey"),
        sa.UniqueConstraint(
            "content",
            "start",
            "belief_time",
            "source_id",
            "type",
            name="annotation_content_key",
        ),
    )
    op.create_table(
        "annotations_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.INTEGER(), nullable=True),
        sa.Column("annotation_id", sa.INTEGER(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
            name="annotations_accounts_account_id_account_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["annotation_id"],
            ["annotation.id"],
            name="annotations_accounts_annotation_id_annotation_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="annotations_accounts_pkey"),
        sa.UniqueConstraint(
            "annotation_id", "account_id", name="annotations_accounts_annotation_id_key"
        ),
    )
    op.create_table(
        "fm_user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.VARCHAR(length=255), nullable=True),
        sa.Column("username", sa.VARCHAR(length=255), nullable=True),
        sa.Column("password", sa.VARCHAR(length=255), nullable=True),
        sa.Column("last_login_at", postgresql.TIMESTAMP(), nullable=True),
        sa.Column("login_count", sa.INTEGER(), nullable=True),
        sa.Column("active", sa.BOOLEAN(), nullable=True),
        sa.Column("timezone", sa.VARCHAR(length=255), nullable=True),
        sa.Column("fs_uniquifier", sa.VARCHAR(length=64), nullable=False),
        sa.Column("account_id", sa.INTEGER(), nullable=False),
        sa.Column("last_seen_at", postgresql.TIMESTAMP(), nullable=True),
        sa.Column("tf_totp_secret", sa.TEXT(), nullable=True),
        sa.Column(
            "tf_primary_method",
            sa.VARCHAR(length=255),
            server_default=sa.text("'email'::character varying"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fm_user_account_id_account_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="fm_user_pkey"),
        sa.UniqueConstraint("email", name="fm_user_email_key"),
        sa.UniqueConstraint("fs_uniquifier", name="fm_user_fs_uniquifier_key"),
        sa.UniqueConstraint("username", name="fm_user_username_key"),
    )
    op.create_table(
        "generic_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.VARCHAR(length=80), nullable=True),
        sa.Column("latitude", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("longitude", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("generic_asset_type_id", sa.INTEGER(), nullable=False),
        sa.Column("account_id", sa.INTEGER(), nullable=True),
        sa.Column(
            "attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("parent_asset_id", sa.INTEGER(), nullable=True),
        sa.Column(
            "sensors_to_show",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "flex_context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "flex_model",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "sensors_to_show_as_kpis",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("external_id", sa.VARCHAR(length=80), nullable=True),
        sa.Column(
            "secrets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("description", sa.TEXT(), nullable=True),
        sa.CheckConstraint(
            "parent_asset_id <> id", name=op.f("generic_asset_self_reference_ck")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
            name="generic_asset_account_id_account_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generic_asset_type_id"],
            ["generic_asset_type.id"],
            name="generic_asset_generic_asset_type_id_generic_asset_type_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["parent_asset_id"],
            ["generic_asset.id"],
            name="generic_asset_parent_asset_id_generic_asset_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="generic_asset_pkey"),
        sa.UniqueConstraint(
            "account_id", "external_id", name="generic_asset_account_id_external_id_key"
        ),
    )
    op.create_index(
        "generic_asset_name_parent_asset_id_key",
        "generic_asset",
        ["name", "parent_asset_id"],
        unique=True,
        postgresql_where="(parent_asset_id IS NOT NULL)",
    )
    op.create_index(
        "generic_asset_public_root_name_key",
        "generic_asset",
        ["name"],
        unique=True,
        postgresql_where="((parent_asset_id IS NULL) AND (account_id IS NULL))",
    )
    op.create_index(
        "generic_asset_root_account_id_name_key",
        "generic_asset",
        ["account_id", "name"],
        unique=True,
        postgresql_where="((parent_asset_id IS NULL) AND (account_id IS NOT NULL))",
    )
    op.create_table(
        "roles_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.INTEGER(), nullable=True),
        sa.Column("role_id", sa.INTEGER(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["account.id"],
            name="roles_accounts_account_id_account_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["account_role.id"],
            name="roles_accounts_role_id_account_role_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="roles_accounts_pkey"),
        sa.UniqueConstraint("role_id", "account_id", name="roles_accounts_role_id_key"),
    )
    op.create_table(
        "annotations_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generic_asset_id", sa.INTEGER(), nullable=True),
        sa.Column("annotation_id", sa.INTEGER(), nullable=True),
        sa.ForeignKeyConstraint(
            ["annotation_id"],
            ["annotation.id"],
            name="annotations_assets_annotation_id_annotation_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generic_asset_id"],
            ["generic_asset.id"],
            name="annotations_assets_generic_asset_id_generic_asset_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="annotations_assets_pkey"),
        sa.UniqueConstraint(
            "annotation_id",
            "generic_asset_id",
            name="annotations_assets_annotation_id_key",
        ),
    )
    op.create_table(
        "asset_audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_datetime", postgresql.TIMESTAMP(), nullable=True),
        sa.Column("event", sa.VARCHAR(length=500), nullable=True),
        sa.Column("active_user_name", sa.VARCHAR(length=255), nullable=True),
        sa.Column("active_user_id", sa.INTEGER(), nullable=True),
        sa.Column("affected_asset_id", sa.INTEGER(), nullable=True),
        sa.ForeignKeyConstraint(
            ["active_user_id"],
            ["fm_user.id"],
            name="asset_audit_log_active_user_id_fm_user_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["affected_asset_id"],
            ["generic_asset.id"],
            name="asset_audit_log_affected_asset_id_generic_asset_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="asset_audit_log_pkey"),
    )
    op.create_table(
        "automation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("asset_id", sa.INTEGER(), nullable=False),
        sa.Column("type", sa.VARCHAR(length=80), nullable=False),
        sa.Column("name", sa.VARCHAR(length=80), nullable=False),
        sa.Column("cronstr", sa.VARCHAR(length=80), nullable=False),
        sa.Column("active", sa.BOOLEAN(), nullable=False),
        sa.Column("generator_id", sa.INTEGER(), nullable=False),
        sa.Column(
            "parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("timezone", sa.VARCHAR(length=64), nullable=False),
        sa.Column("cursor", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["generic_asset.id"],
            name="automation_asset_id_generic_asset_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generator_id"],
            ["data_source.id"],
            name="automation_generator_id_data_source_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="automation_pkey"),
    )
    op.create_index("ix_automation_asset_id", "automation", ["asset_id"], unique=False)
    op.create_table(
        "roles_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.INTEGER(), nullable=True),
        sa.Column("role_id", sa.INTEGER(), nullable=True),
        sa.ForeignKeyConstraint(
            ["role_id"], ["role.id"], name="bvp_roles_users_role_id_bvp_roles_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["fm_user.id"], name="bvp_roles_users_user_id_bvp_users_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="bvp_roles_users_pkey"),
        sa.UniqueConstraint("role_id", "user_id", name="roles_users_role_id_key"),
    )
    op.create_table(
        "sensor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.VARCHAR(length=120), nullable=False),
        sa.Column("unit", sa.VARCHAR(length=80), nullable=False),
        sa.Column("timezone", sa.VARCHAR(length=80), nullable=False),
        sa.Column("event_resolution", postgresql.INTERVAL(), nullable=False),
        sa.Column("knowledge_horizon_fnc", sa.VARCHAR(length=80), nullable=False),
        sa.Column(
            "knowledge_horizon_par",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("generic_asset_id", sa.INTEGER(), nullable=False),
        sa.Column(
            "attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["generic_asset_id"],
            ["generic_asset.id"],
            name="sensor_generic_asset_id_generic_asset_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="sensor_pkey"),
        sa.UniqueConstraint(
            "name", "generic_asset_id", name="sensor_name_generic_asset_id_key"
        ),
    )
    op.create_table(
        "annotations_sensors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sensor_id", sa.INTEGER(), nullable=True),
        sa.Column("annotation_id", sa.INTEGER(), nullable=True),
        sa.ForeignKeyConstraint(
            ["annotation_id"],
            ["annotation.id"],
            name="annotations_sensors_annotation_id_annotation_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sensor_id"],
            ["sensor.id"],
            name="annotations_sensors_sensor_id_sensor_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="annotations_sensors_pkey"),
        sa.UniqueConstraint(
            "annotation_id", "sensor_id", name="annotations_sensors_annotation_id_key"
        ),
    )
    op.create_table(
        "sensor_data_source",
        sa.Column("sensor_id", sa.INTEGER(), nullable=False),
        sa.Column("source_id", sa.INTEGER(), nullable=False),
        sa.ForeignKeyConstraint(
            ["sensor_id"],
            ["sensor.id"],
            name="sensor_data_source_sensor_id_sensor_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_source.id"],
            name="sensor_data_source_source_id_data_source_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "sensor_id", "source_id", name="sensor_data_source_pkey"
        ),
    )
    op.create_table(
        "timed_belief",
        sa.Column("event_start", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("belief_horizon", postgresql.INTERVAL(), nullable=False),
        sa.Column(
            "cumulative_probability", sa.DOUBLE_PRECISION(precision=53), nullable=False
        ),
        sa.Column("event_value", sa.DOUBLE_PRECISION(precision=53), nullable=False),
        sa.Column("sensor_id", sa.INTEGER(), nullable=False),
        sa.Column("source_id", sa.INTEGER(), nullable=False),
        sa.ForeignKeyConstraint(
            ["sensor_id"],
            ["sensor.id"],
            name="timed_belief_sensor_id_sensor_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_source.id"],
            name="timed_belief_source_id_data_source_fkey",
        ),
        sa.PrimaryKeyConstraint(
            "sensor_id",
            "source_id",
            "event_start",
            "belief_horizon",
            "cumulative_probability",
            name="timed_belief_pkey",
        ),
    )
    op.create_index(
        "timed_belief_search_session_idx",
        "timed_belief",
        ["event_start", "sensor_id", "source_id"],
        unique=False,
        postgresql_include=["belief_horizon"],
    )
    op.create_index(
        "timed_belief_search_session_singleevent_idx",
        "timed_belief",
        ["sensor_id", "event_start"],
        unique=False,
    )

    # Install the summary trigger, sharing the definitions with the model layer,
    # so that a schema built by migrations and one built by create_all() cannot drift apart.
    op.execute(sa.text(RECORD_SENSOR_DATA_SOURCES_FUNCTION))
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS timed_belief_record_sensor_data_sources"
            " ON timed_belief"
        )
    )
    op.execute(sa.text(RECORD_SENSOR_DATA_SOURCES_TRIGGER))


def downgrade():
    raise NotImplementedError(DOWNGRADE_MESSAGE)
