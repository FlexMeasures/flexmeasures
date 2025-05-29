import pytest
from sqlalchemy import select, func

from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource

from flexmeasures.cli.tests.utils import (
    check_command_ran_without_error,
    get_click_commands,
)


@pytest.mark.skip_github
def test_add_annotation(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_annotation

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


@pytest.mark.skip_github
def test_add_holidays(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_holidays

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
