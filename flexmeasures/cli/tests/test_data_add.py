from flexmeasures.cli.tests.utils import to_flags
from flexmeasures.data.models.annotations import (
    Annotation,
    AccountAnnotationRelationship,
)
from flexmeasures.data.models.data_sources import DataSource


def test_add_annotation(cli_app, cli_db, setup_mdc_account_owner):
    from flexmeasures.cli.data_add import add_annotation

    user = setup_mdc_account_owner["Test Account Owner"]
    account = user.account
    print(user.id)
    print(account.id)

    cli_input = {
        "content": "Company founding day",
        "at": "2016-05-11T00:00+02:00",
        "account-id": account.id,
        "user-id": user.id,
    }
    runner = cli_app.test_cli_runner()
    result = runner.invoke(add_annotation, to_flags(cli_input))
    raise
    # Check result for success
    assert "Successfully added annotation" in result.output

    # Check database for annotation entry
    assert (
        Annotation.query.filter(
            Annotation.content == cli_input["content"],
            Annotation.start == cli_input["at"],
        )
        .join(AccountAnnotationRelationship)
        .filter(
            AccountAnnotationRelationship.account_id == cli_input["account-id"],
            AccountAnnotationRelationship.annotation_id == Annotation.id,
        )
        .join(DataSource)
        .filter(
            DataSource.id == Annotation.source_id,
            DataSource.user_id == cli_input["user-id"],
        )
        .one_or_none()
    )
