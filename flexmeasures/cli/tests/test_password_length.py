"""`flexmeasures add user` needs a password of at least 12 characters."""

import pytest
from flexmeasures.data.services.users import find_user_by_email


@pytest.mark.parametrize(
    "password, created",
    [("elevenchars", False), ("twelve-chars", True)],
)
def test_add_user_requires_a_long_enough_password(
    app, db, setup_accounts, monkeypatch, password, created
):
    from flexmeasures.cli.data_add import new_user

    monkeypatch.setattr("getpass.getpass", lambda prompt="": password)
    email = f"password-length-{len(password)}@example.com"
    result = app.test_cli_runner().invoke(
        new_user,
        [
            "--username",
            f"password-length-{len(password)}",
            "--email",
            email,
            "--account",
            str(setup_accounts["Prosumer"].id),
            "--timezone",
            "UTC",
        ],
    )
    assert (result.exit_code == 0) == created, result.output
    assert (find_user_by_email(email) is not None) == created
