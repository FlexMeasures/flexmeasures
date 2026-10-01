"""Couple a data generator's data source to the organisation it runs for

Revision ID: c5e1a7b94d20
Revises: b63a02d5e184
Create Date: 2026-10-01 14:40:00.000000

A data source carries an ``account_id``, but until now only sources of type ``user`` ever got one:
nothing on the generator side passed an organisation to ``get_or_create_source``.
Two organisations running the same generator under the same configuration therefore shared one source row.

From this release the organisation is part of what identifies a source, so the sources that already exist have to say which organisation they recorded for,
or the first run after the upgrade will not recognise them and will create a second source beside each one.

Which organisation that is can be read off the data: a belief's sensor belongs to an asset, and that asset names the organisation.
The same goes for annotations, and for the asset an automation hangs off, which covers a source whose automation has not run yet.
A source with one organisation among those signals has its column filled in place, keeping its id, so that nothing pointing at it has to change.
A source with none keeps no organisation, which is what a generator the host runs for everyone looks like.

A source shared by several organisations cannot be filled in place, and this migration does not guess.
It stops and names the sources and the organisations sharing them, and the same command splits them when told to:

    flexmeasures db upgrade -x split-shared-sources=true

A split keeps the source id for the organisation whose beliefs under it are the freshest, since a source id is something installations pin,
and moves the other organisations' beliefs, annotations, sensor links and automations onto newly created sources of their own.
"""

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c5e1a7b94d20"
down_revision = "b63a02d5e184"
branch_labels = None
depends_on = None


# Every way in which a data source says which organisation it recorded for.
# These are unioned rather than ranked: where two of them disagree, the source really is shared,
# which is the case a host has to look at rather than one to resolve by precedence.
ORGANISATION_SIGNALS = """
    SELECT sds.source_id AS source_id, ga.account_id AS account_id
      FROM sensor_data_source sds
      JOIN sensor s ON s.id = sds.sensor_id
      JOIN generic_asset ga ON ga.id = s.generic_asset_id
    UNION
    SELECT a.generator_id AS source_id, ga.account_id AS account_id
      FROM automation a
      JOIN generic_asset ga ON ga.id = a.asset_id
    UNION
    SELECT an.source_id AS source_id, aa.account_id AS account_id
      FROM annotation an
      JOIN annotations_accounts aa ON aa.annotation_id = an.id
    UNION
    SELECT an.source_id AS source_id, ga.account_id AS account_id
      FROM annotation an
      JOIN annotations_assets aga ON aga.annotation_id = an.id
      JOIN generic_asset ga ON ga.id = aga.generic_asset_id
    UNION
    SELECT an.source_id AS source_id, ga.account_id AS account_id
      FROM annotation an
      JOIN annotations_sensors ans ON ans.annotation_id = an.id
      JOIN sensor s ON s.id = ans.sensor_id
      JOIN generic_asset ga ON ga.id = s.generic_asset_id
"""


def _organisations_per_source(connection) -> dict[int, set[int]]:
    """Which organisations each data source without one recorded for, by the evidence in the data."""
    rows = connection.execute(sa.text(f"""
            WITH signals AS ({ORGANISATION_SIGNALS})
            SELECT signals.source_id, signals.account_id
              FROM signals
              JOIN data_source ds ON ds.id = signals.source_id
             WHERE signals.account_id IS NOT NULL
               AND ds.account_id IS NULL
               AND ds.user_id IS NULL
            """)).fetchall()
    per_source: dict[int, set[int]] = {}
    for source_id, account_id in rows:
        per_source.setdefault(source_id, set()).add(account_id)
    return per_source


def _describe(connection, source_ids: list[int]) -> dict[int, str]:
    """A readable name per source, for the message a host has to act on."""
    if not source_ids:
        return {}
    rows = connection.execute(
        sa.text(
            "SELECT id, name, type, model, version FROM data_source WHERE id = ANY(:ids)"
        ),
        {"ids": source_ids},
    ).fetchall()
    return {
        row[0]: f"{row[1]} ({row[2]}"
        + (f", {row[3]}" if row[3] else "")
        + (f" v{row[4]}" if row[4] else "")
        + ")"
        for row in rows
    }


def _freshest_belief_per_organisation(
    connection, source_id: int, account_ids: set[int]
) -> list[int]:
    """The organisations sharing a source, the one whose beliefs under it are freshest first.

    The source keeps its id for that one, because a source id is something installations pin:
    it turns up in `sources` filters inside flex-model and flex-context references, and in automation parameters.
    """
    rows = connection.execute(
        sa.text("""
            SELECT ga.account_id, MAX(tb.event_start) AS latest
              FROM timed_belief tb
              JOIN sensor s ON s.id = tb.sensor_id
              JOIN generic_asset ga ON ga.id = s.generic_asset_id
             WHERE tb.source_id = :source_id
               AND ga.account_id = ANY(:account_ids)
             GROUP BY ga.account_id
             ORDER BY latest DESC
            """),
        {"source_id": source_id, "account_ids": list(account_ids)},
    ).fetchall()
    ranked = [row[0] for row in rows]
    # An organisation with no beliefs under the source at all still has a claim through an automation or an annotation,
    # but no claim to the id, so it goes last.
    return ranked + sorted(account_ids - set(ranked))


def _sensors_of(connection, account_id: int) -> list[int]:
    return [
        row[0]
        for row in connection.execute(
            sa.text("""
                SELECT s.id FROM sensor s
                  JOIN generic_asset ga ON ga.id = s.generic_asset_id
                 WHERE ga.account_id = :account_id
                """),
            {"account_id": account_id},
        ).fetchall()
    ]


def _split_source(connection, source_id: int, account_id: int) -> int:
    """Give one organisation its own copy of a shared source, and move what it recorded onto it."""
    new_source_id = connection.execute(
        sa.text("""
            INSERT INTO data_source (name, type, model, version, attributes, attributes_hash, account_id)
            SELECT name, type, model, version, attributes, attributes_hash, :account_id
              FROM data_source WHERE id = :source_id
            RETURNING id
            """),
        {"source_id": source_id, "account_id": account_id},
    ).scalar_one()
    sensor_ids = _sensors_of(connection, account_id)
    if sensor_ids:
        # Naming the sensors keeps these statements on the `timed_belief` primary key,
        # rather than scanning what is typically the largest table in the database.
        connection.execute(
            sa.text("""
                UPDATE timed_belief SET source_id = :new_source_id
                 WHERE source_id = :source_id AND sensor_id = ANY(:sensor_ids)
                """),
            {
                "new_source_id": new_source_id,
                "source_id": source_id,
                "sensor_ids": sensor_ids,
            },
        )
        connection.execute(
            sa.text("""
                UPDATE sensor_data_source SET source_id = :new_source_id
                 WHERE source_id = :source_id AND sensor_id = ANY(:sensor_ids)
                """),
            {
                "new_source_id": new_source_id,
                "source_id": source_id,
                "sensor_ids": sensor_ids,
            },
        )
        connection.execute(
            sa.text("""
                UPDATE annotation SET source_id = :new_source_id
                 WHERE source_id = :source_id
                   AND id IN (SELECT annotation_id FROM annotations_sensors WHERE sensor_id = ANY(:sensor_ids))
                """),
            {
                "new_source_id": new_source_id,
                "source_id": source_id,
                "sensor_ids": sensor_ids,
            },
        )
    connection.execute(
        sa.text("""
            UPDATE annotation SET source_id = :new_source_id
             WHERE source_id = :source_id
               AND (
                   id IN (SELECT annotation_id FROM annotations_accounts WHERE account_id = :account_id)
                   OR id IN (
                       SELECT aga.annotation_id FROM annotations_assets aga
                         JOIN generic_asset ga ON ga.id = aga.generic_asset_id
                        WHERE ga.account_id = :account_id
                   )
               )
            """),
        {
            "new_source_id": new_source_id,
            "source_id": source_id,
            "account_id": account_id,
        },
    )
    connection.execute(
        sa.text("""
            UPDATE automation SET generator_id = :new_source_id
             WHERE generator_id = :source_id
               AND asset_id IN (SELECT id FROM generic_asset WHERE account_id = :account_id)
            """),
        {
            "new_source_id": new_source_id,
            "source_id": source_id,
            "account_id": account_id,
        },
    )
    return new_source_id


def _keepers_from_x_arguments(arguments: list[str]) -> dict[int, int]:
    """Read `-x keep-source=<source id>:<organisation id>`, which a host can repeat per shared source.

    Naming the organisation that keeps a source's id is something only the host can answer,
    since a source id can be referred to from configurations FlexMeasures cannot interpret for them.
    """
    keepers: dict[int, int] = {}
    for argument in arguments:
        if not argument.startswith("keep-source="):
            continue
        value = argument.split("=", 1)[1]
        try:
            source_id, account_id = (int(part) for part in value.split(":", 1))
        except ValueError:
            raise RuntimeError(
                f"Could not read -x keep-source={value}; it takes a source id and an organisation id, as in -x keep-source=42:3."
            )
        keepers[source_id] = account_id
    return keepers


def upgrade():
    arguments = context.get_x_argument()
    splitting = any(
        argument.lower() in ("split-shared-sources=true", "split-shared-sources=yes")
        for argument in arguments
    )
    couple_sources_to_organisations(
        op.get_bind(),
        splitting=splitting,
        keepers=_keepers_from_x_arguments(list(arguments)),
    )


def couple_sources_to_organisations(
    connection, splitting: bool, keepers: dict[int, int] | None = None
) -> None:
    """Couple each data source to the organisation it recorded for, splitting the shared ones only when told to.

    Kept apart from `upgrade` so that it can be run against a connection in a test,
    which is worth doing for a migration that moves beliefs between sources.
    """
    per_source = _organisations_per_source(connection)
    single = {
        source_id: next(iter(accounts))
        for source_id, accounts in per_source.items()
        if len(accounts) == 1
    }
    shared = {
        source_id: accounts
        for source_id, accounts in per_source.items()
        if len(accounts) > 1
    }

    for source_id, account_id in single.items():
        connection.execute(
            sa.text(
                "UPDATE data_source SET account_id = :account_id WHERE id = :source_id"
            ),
            {"account_id": account_id, "source_id": source_id},
        )
    if single:
        print(
            f"Coupled {len(single)} data source(s) to the organisation they recorded for."
        )

    if not shared:
        _report_unowned(connection)
        return

    names = _describe(connection, list(shared))
    if not splitting:
        lines = [
            f"  data source {source_id} ({names.get(source_id, 'unknown')}): organisations {sorted(accounts)}"
            for source_id, accounts in sorted(shared.items())
        ]
        raise RuntimeError(
            "These data sources recorded for more than one organisation, so they cannot be coupled to one:\n"
            + "\n".join(lines)
            + "\n\nSplitting them keeps each source id for the organisation whose beliefs under it are the freshest,"
            "\nand moves what the other organisations recorded onto new sources of their own."
            "\nRun the same upgrade with:\n\n"
            "    flexmeasures db upgrade -x split-shared-sources=true\n"
            "\nA source id can be referred to from configurations this upgrade cannot read, such as a `sources` filter in a flex-context,"
            "\nso name the organisation that keeps one yourself where freshness is the wrong answer:\n\n"
            "    flexmeasures db upgrade -x split-shared-sources=true -x keep-source=42:3\n"
        )

    keepers = keepers or {}
    unknown = set(keepers) - set(shared)
    if unknown:
        raise RuntimeError(
            f"Asked to keep data source(s) {sorted(unknown)} with a named organisation, but they are not shared by several organisations."
        )
    for source_id, accounts in sorted(shared.items()):
        ranked = _freshest_belief_per_organisation(connection, source_id, accounts)
        named = keepers.get(source_id)
        if named is not None and named not in accounts:
            raise RuntimeError(
                f"Asked to keep data source {source_id} with organisation {named}, which did not record under it."
                f" It was shared by organisations {sorted(accounts)}."
            )
        keeps_id = named if named is not None else ranked[0]
        moved = [account_id for account_id in ranked if account_id != keeps_id]
        connection.execute(
            sa.text(
                "UPDATE data_source SET account_id = :account_id WHERE id = :source_id"
            ),
            {"account_id": keeps_id, "source_id": source_id},
        )
        reason = (
            "as asked"
            if named is not None
            else "which has the freshest beliefs under it"
        )
        print(
            f"Data source {source_id} ({names.get(source_id, 'unknown')}) was shared by organisations {sorted(accounts)}."
            f" It stays with organisation {keeps_id}, {reason}."
        )
        for account_id in moved:
            new_source_id = _split_source(connection, source_id, account_id)
            print(
                f"  organisation {account_id} now records under new data source {new_source_id}."
            )

    _report_unowned(connection)


def _report_unowned(connection) -> None:
    """Say how many sources end the upgrade belonging to no organisation.

    That is the right answer for a generator the host runs for everyone,
    and it is also what a worker still running the previous version leaves behind,
    so a host who sees this number grow afterwards knows one was still writing.
    """
    left_unowned = connection.execute(sa.text("""
            SELECT COUNT(*) FROM data_source
             WHERE account_id IS NULL AND user_id IS NULL AND type <> 'user'
            """)).scalar_one()
    if left_unowned:
        print(
            f"{left_unowned} data source(s) belong to no organisation, which is what a generator the host runs for everyone looks like."
            " If that number grows after this upgrade, a worker was still running the previous version."
        )


def downgrade():
    """Uncouple every data source that names no user, which is what the generator sources looked like before.

    A source that was split keeps existing, because its beliefs now point at it;
    downgrading leaves both rows in place, uncoupled, which is the state the old code reads.
    """
    op.execute(
        "UPDATE data_source SET account_id = NULL WHERE user_id IS NULL AND type <> 'user'"
    )
