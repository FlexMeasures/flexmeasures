import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from flexmeasures.data.models.task_runs import LatestTaskRun
from flexmeasures.data.models.user import User


def test_monitor_help(app):
    from flexmeasures.cli.monitor import (
        fm_monitor,
        monitor_last_seen,
        monitor_latest_run,
    )

    runner = app.test_cli_runner()

    result = runner.invoke(fm_monitor, ["--help"])
    assert result.exit_code == 0

    for command in (monitor_last_seen, monitor_latest_run):
        result = runner.invoke(command, ["--help"])

        assert result.exit_code == 0
        assert "--inform-this-user" in result.output
    result = runner.invoke(monitor_last_seen, ["--help"])
    assert "--account" in result.output


def test_get_default_monitoring_email_recipients_prefers_new_config(app, monkeypatch):
    from flexmeasures.cli import monitor

    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS",
        "new@example.test",
    )
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_MONITORING_MAIL_RECIPIENTS",
        ["old@example.test"],
    )

    assert monitor.get_default_monitoring_email_recipients() == ["new@example.test"]


def test_get_default_monitoring_email_recipients_falls_back_to_deprecated_config(
    app, monkeypatch
):
    from flexmeasures.cli import monitor

    monkeypatch.setitem(
        app.config, "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS", []
    )
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_MONITORING_MAIL_RECIPIENTS",
        "old@example.test",
    )

    assert monitor.get_default_monitoring_email_recipients() == ["old@example.test"]


def test_monitor_latest_run_informs_requested_users(
    app, fresh_db, setup_roles_users_fresh_db, monkeypatch
):
    from flexmeasures.cli import monitor
    from flexmeasures.cli.monitor import monitor_latest_run

    monkeypatch.setattr(monitor, "capture_message_for_sentry", lambda msg: None)
    monkeypatch.setattr(monitor, "set_sentry_context", lambda *args, **kwargs: None)
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS",
        ["ops@example.test"],
    )
    first_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Prosumer User"]
    )
    second_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Supplier User"]
    )
    fresh_db.session.add(
        LatestTaskRun(
            name="import-data",
            datetime=datetime.now(timezone.utc) - timedelta(minutes=5),
            status=False,
        )
    )
    fresh_db.session.commit()

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_latest_run,
            [
                "--task",
                "import-data",
                "10",
                "--inform-this-user",
                str(first_user.id),
                "--inform-this-user",
                str(second_user.id),
            ],
        )

    assert result.exit_code == 0
    assert len(outbox) == 1
    assert outbox[0].bcc == [first_user.email, second_user.email]


def test_monitor_latest_run_informs_requested_user_by_email(
    app, fresh_db, setup_roles_users_fresh_db, monkeypatch
):
    from flexmeasures.cli import monitor
    from flexmeasures.cli.monitor import monitor_latest_run

    monkeypatch.setattr(monitor, "capture_message_for_sentry", lambda msg: None)
    monkeypatch.setattr(monitor, "set_sentry_context", lambda *args, **kwargs: None)
    informed_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Supplier User"]
    )
    fresh_db.session.add(
        LatestTaskRun(
            name="import-data",
            datetime=datetime.now(timezone.utc) - timedelta(minutes=5),
            status=False,
        )
    )
    fresh_db.session.commit()

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_latest_run,
            [
                "--task",
                "import-data",
                "10",
                "--inform-this-user",
                informed_user.email,
            ],
        )

    assert result.exit_code == 0
    assert len(outbox) == 1
    assert outbox[0].bcc == [informed_user.email]


def test_monitor_latest_run_informs_requested_users_by_mixed_identifiers(
    app, fresh_db, setup_roles_users_fresh_db, monkeypatch
):
    from flexmeasures.cli import monitor
    from flexmeasures.cli.monitor import monitor_latest_run

    monkeypatch.setattr(monitor, "capture_message_for_sentry", lambda msg: None)
    monkeypatch.setattr(monitor, "set_sentry_context", lambda *args, **kwargs: None)
    first_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Prosumer User"]
    )
    second_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Supplier User"]
    )
    fresh_db.session.add(
        LatestTaskRun(
            name="import-data",
            datetime=datetime.now(timezone.utc) - timedelta(minutes=5),
            status=False,
        )
    )
    fresh_db.session.commit()

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_latest_run,
            [
                "--task",
                "import-data",
                "10",
                "--inform-this-user",
                str(first_user.id),
                "--inform-this-user",
                second_user.email,
            ],
        )

    assert result.exit_code == 0
    assert len(outbox) == 1
    assert outbox[0].bcc == [first_user.email, second_user.email]


def test_monitor_latest_run_rejects_unknown_informed_user(app, fresh_db):
    from flexmeasures.cli.monitor import monitor_latest_run

    result = app.test_cli_runner().invoke(
        monitor_latest_run,
        ["--task", "import-data", "10", "--inform-this-user", "9999"],
    )

    assert result.exit_code != 0
    assert "No user with ID or email address 9999 exists" in result.output


def test_monitor_latest_run_rejects_unknown_informed_user_email(app, fresh_db):
    from flexmeasures.cli.monitor import monitor_latest_run

    result = app.test_cli_runner().invoke(
        monitor_latest_run,
        [
            "--task",
            "import-data",
            "10",
            "--inform-this-user",
            "missing@example.test",
        ],
    )

    assert result.exit_code != 0
    assert (
        "No user with ID or email address missing@example.test exists" in result.output
    )


def test_monitor_last_seen_uses_deprecated_config_fallback(
    app, fresh_db, setup_roles_users_fresh_db, monkeypatch
):
    from flexmeasures.cli import monitor
    from flexmeasures.cli.monitor import monitor_last_seen

    monkeypatch.setattr(monitor, "capture_message_for_sentry", lambda msg: None)
    monkeypatch.setattr(monitor, "set_sentry_context", lambda *args, **kwargs: None)
    monkeypatch.setitem(
        app.config, "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS", []
    )
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_MONITORING_MAIL_RECIPIENTS",
        ["ops@example.test"],
    )
    absent_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Prosumer User"]
    )
    absent_user.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=120)
    fresh_db.session.commit()

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_last_seen,
            [
                "--maximum-minutes-since-last-seen",
                "30",
                "--all-absent-users",
            ],
        )

    assert result.exit_code == 0
    assert len(outbox) == 1
    assert outbox[0].bcc == ["ops@example.test"]


def test_monitor_last_seen_filters_users_by_account_id(
    app, fresh_db, setup_roles_users_fresh_db, setup_accounts_fresh_db, monkeypatch
):
    from flexmeasures.cli import monitor
    from flexmeasures.cli.monitor import monitor_last_seen

    monkeypatch.setattr(monitor, "capture_message_for_sentry", lambda msg: None)
    monkeypatch.setattr(monitor, "set_sentry_context", lambda *args, **kwargs: None)
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS",
        ["ops@example.test"],
    )
    for user in fresh_db.session.scalars(select(User)).all():
        user.last_seen_at = datetime.now(timezone.utc)
    prosumer_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Prosumer User"]
    )
    supplier_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Supplier User"]
    )
    prosumer_user.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=120)
    supplier_user.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=120)
    fresh_db.session.commit()

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_last_seen,
            [
                "--maximum-minutes-since-last-seen",
                "30",
                "--all-absent-users",
                "--account",
                str(setup_accounts_fresh_db["Prosumer"].id),
            ],
        )

    assert result.exit_code == 0
    assert len(outbox) == 1
    assert "User ID" in outbox[0].body
    assert "Account ID" in outbox[0].body
    assert re.search(
        rf"^{prosumer_user.username}\s+{prosumer_user.id}\s+{prosumer_user.account_id}\s+",
        outbox[0].body,
        flags=re.MULTILINE,
    )
    assert prosumer_user.username in outbox[0].body
    assert supplier_user.username not in outbox[0].body
    assert f"account has ID {setup_accounts_fresh_db['Prosumer'].id}" in outbox[0].body


def test_monitor_last_seen_combines_account_id_and_user_role_filters(
    app, fresh_db, setup_roles_users_fresh_db, setup_accounts_fresh_db, monkeypatch
):
    from flexmeasures.cli import monitor
    from flexmeasures.cli.monitor import monitor_last_seen

    monkeypatch.setattr(monitor, "capture_message_for_sentry", lambda msg: None)
    monkeypatch.setattr(monitor, "set_sentry_context", lambda *args, **kwargs: None)
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS",
        ["ops@example.test"],
    )
    plain_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Prosumer User"]
    )
    account_admin = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Prosumer User 2"]
    )
    plain_user.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=120)
    account_admin.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=120)
    fresh_db.session.commit()

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_last_seen,
            [
                "--maximum-minutes-since-last-seen",
                "30",
                "--all-absent-users",
                "--account",
                str(setup_accounts_fresh_db["Prosumer"].id),
                "--user-role",
                "account-admin",
            ],
        )

    assert result.exit_code == 0
    assert len(outbox) == 1
    assert account_admin.username in outbox[0].body
    assert f"{plain_user.username}  " not in outbox[0].body


def test_monitor_last_seen_without_account_id_reports_users_from_all_accounts(
    app, fresh_db, setup_roles_users_fresh_db, monkeypatch
):
    from flexmeasures.cli import monitor
    from flexmeasures.cli.monitor import monitor_last_seen

    monkeypatch.setattr(monitor, "capture_message_for_sentry", lambda msg: None)
    monkeypatch.setattr(monitor, "set_sentry_context", lambda *args, **kwargs: None)
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS",
        ["ops@example.test"],
    )
    for user in fresh_db.session.scalars(select(User)).all():
        user.last_seen_at = datetime.now(timezone.utc)
    prosumer_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Prosumer User"]
    )
    supplier_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Supplier User"]
    )
    prosumer_user.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=120)
    supplier_user.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=180)
    fresh_db.session.commit()

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_last_seen,
            [
                "--maximum-minutes-since-last-seen",
                "30",
                "--all-absent-users",
            ],
        )

    assert result.exit_code == 0
    assert len(outbox) == 1
    assert prosumer_user.username in outbox[0].body
    assert supplier_user.username in outbox[0].body
    assert outbox[0].body.index(supplier_user.username) < outbox[0].body.index(
        prosumer_user.username
    )


def test_monitor_last_seen_rejects_unknown_account_id(app, fresh_db):
    from flexmeasures.cli.monitor import monitor_last_seen

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_last_seen,
            [
                "--maximum-minutes-since-last-seen",
                "30",
                "--account",
                "9999",
            ],
        )

    assert result.exit_code != 0
    assert "No account found with id 9999" in result.output
    assert len(outbox) == 0


def test_monitor_last_seen_informs_requested_user(
    app, fresh_db, setup_roles_users_fresh_db, monkeypatch
):
    from flexmeasures.cli import monitor
    from flexmeasures.cli.monitor import monitor_last_seen

    monkeypatch.setattr(monitor, "capture_message_for_sentry", lambda msg: None)
    monkeypatch.setattr(monitor, "set_sentry_context", lambda *args, **kwargs: None)
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_DEFAULT_MONITORING_MAIL_RECIPIENTS",
        ["ops@example.test"],
    )
    absent_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Prosumer User"]
    )
    informed_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Supplier User"]
    )
    absent_user.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=120)
    fresh_db.session.commit()

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_last_seen,
            [
                "--maximum-minutes-since-last-seen",
                "30",
                "--all-absent-users",
                "--inform-this-user",
                str(informed_user.id),
            ],
        )

    assert result.exit_code == 0
    assert len(outbox) == 1
    assert outbox[0].bcc == [informed_user.email]


def test_monitor_last_seen_informs_requested_user_by_email(
    app, fresh_db, setup_roles_users_fresh_db, monkeypatch
):
    from flexmeasures.cli import monitor
    from flexmeasures.cli.monitor import monitor_last_seen

    monkeypatch.setattr(monitor, "capture_message_for_sentry", lambda msg: None)
    monkeypatch.setattr(monitor, "set_sentry_context", lambda *args, **kwargs: None)
    absent_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Prosumer User"]
    )
    informed_user = fresh_db.session.get(
        User, setup_roles_users_fresh_db["Test Supplier User"]
    )
    absent_user.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=120)
    fresh_db.session.commit()

    with app.mail.record_messages() as outbox:
        result = app.test_cli_runner().invoke(
            monitor_last_seen,
            [
                "--maximum-minutes-since-last-seen",
                "30",
                "--all-absent-users",
                "--inform-this-user",
                informed_user.email,
            ],
        )

    assert result.exit_code == 0
    assert len(outbox) == 1
    assert outbox[0].bcc == [informed_user.email]
