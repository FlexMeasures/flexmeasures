from sqlalchemy import select, func

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.user import Plan, RateLimitKey

from flexmeasures.cli.tests.utils import (
    check_command_ran_without_error,
    get_click_commands,
)


def test_add_annotation(app, fresh_db, setup_roles_users_fresh_db):
    from flexmeasures.cli.data_add import add_annotation

    db = fresh_db
    cli_input = {
        "content": "Company founding day",
        "at": "2016-05-11T00:00+02:00",
        "account": 1,
        "user": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_annotation, to_flags(cli_input))

    # Check result for success
    assert "Successfully added annotation" in result.output

    # Check database for annotation entry
    assert db.session.execute(
        select(Annotation)
        .filter_by(
            content=cli_input["content"],
            start=cli_input["at"],
        )
        .join(AccountAnnotationRelationship)
        .filter_by(
            account_id=cli_input["account"],
            annotation_id=Annotation.id,
        )
        .join(DataSource)
        .filter_by(
            id=Annotation.source_id,
            user_id=cli_input["user"],
        )
    ).scalar_one_or_none()


def test_add_plan(app, fresh_db):
    from flexmeasures.cli.data_add import new_plan

    db = fresh_db
    cli_input = {
        "name": "Pro",
        "trigger-rate-limit": "60 per 5 minutes",
        "rate-limit-key": "account",
        "max-assets": 200,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(new_plan, to_flags(cli_input))

    check_command_ran_without_error(result)
    assert "successfully created" in result.output

    plan = db.session.execute(select(Plan).filter_by(name="Pro")).scalar_one()
    assert plan.trigger_rate_limit == "60 per 5 minutes"
    assert plan.rate_limit_key == RateLimitKey.ACCOUNT
    assert plan.max_assets == 200
    # Fields we did not set fall back on the server-wide config settings
    assert plan.default_rate_limit is None
    assert plan.legacy is False


def test_add_plan_with_invalid_rate_limit(app, fresh_db):
    """A limit string we cannot make sense of is caught when the plan is created,
    rather than when a request comes in."""
    from flexmeasures.cli.data_add import new_plan

    db = fresh_db
    runner = app.test_cli_runner()
    result = runner.invoke(
        new_plan, to_flags({"name": "Typo", "trigger-rate-limit": "10 per fortnight"})
    )

    assert result.exit_code != 0
    assert "not a valid rate limit" in result.output
    assert db.session.execute(select(Plan).filter_by(name="Typo")).scalar() is None


def test_edit_plan(app, fresh_db):
    """A plan can be retired, so that it is no longer handed out."""
    from flexmeasures.cli.data_edit import edit_plan

    db = fresh_db
    plan = Plan(name="Pro", trigger_rate_limit="60 per 5 minutes")
    db.session.add(plan)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(edit_plan, ["--name", "Pro", "--legacy"])

    check_command_ran_without_error(result)
    assert db.session.execute(select(Plan).filter_by(name="Pro")).scalar_one().legacy


def test_add_holidays(app, fresh_db, setup_roles_users_fresh_db):
    from flexmeasures.cli.data_add import add_holidays

    db = fresh_db
    cli_input = {
        "year": 2020,
        "country": "NL",
        "account": 1,
    }
    runner = app.test_cli_runner()
    result = runner.invoke(add_holidays, to_flags(cli_input))

    # Check result for 11 public holidays
    assert "'NL': 11" in result.output

    # Check database for 11 annotation entries
    assert (
        db.session.scalar(
            select(func.count())
            .select_from(Annotation)
            .join(AccountAnnotationRelationship)
            .filter(
                AccountAnnotationRelationship.account_id == cli_input["account"],
                AccountAnnotationRelationship.annotation_id == Annotation.id,
            )
            .join(DataSource)
            .filter(
                DataSource.id == Annotation.source_id,
                DataSource.name == "workalendar",
                DataSource.model == cli_input["country"],
            )
        )
        == 11
    )


def test_cli_help(app):
    """Test that showing help does not throw an error."""
    from flexmeasures.cli import data_add

    runner = app.test_cli_runner()
    for cmd in get_click_commands(data_add):
        result = runner.invoke(cmd, ["--help"])
        check_command_ran_without_error(result)
        assert "Usage" in result.output
