from contextlib import contextmanager
import pytest
from typing import Dict

from flexmeasures.app import create as create_app
from flexmeasures.auth.policy import ADMIN_ROLE
from flexmeasures.data.services.users import Account, create_user, User


@pytest.fixture(scope="session")
def cli_app():
    print("APP FIXTURE")
    test_app = create_app(env="testing")

    # Establish an application context before running the tests.
    ctx = test_app.app_context()
    ctx.push()

    yield test_app

    ctx.pop()

    print("DONE WITH APP FIXTURE")


@pytest.fixture(scope="module")
def cli_db(cli_app):
    """Fresh test db per module."""
    with create_test_cli_db(cli_app) as test_db:
        yield test_db


@pytest.fixture(scope="module")
def setup_mdc_account(cli_db) -> Dict[str, Account]:
    mdc_account = Account(
        name="Test MDC Account",
    )
    cli_db.session.add(mdc_account)
    return {mdc_account.name: mdc_account}


@pytest.fixture(scope="module")
def setup_mdc_account_owner(cli_db, setup_mdc_account) -> Dict[str, User]:
    account_owner = create_user(
        username="Test Account Owner",
        email="test_account_owner@seita.nl",
        account_name=setup_mdc_account["Test MDC Account"].name,
        password="testtest",
        # TODO: change ADMIN_ROLE to ACCOUNT_ADMIN
        user_roles=dict(
            name=ADMIN_ROLE, description="A user who can do everything."
        ),
    )
    print(account_owner.account)
    return {account_owner.username: account_owner}


@contextmanager
def create_test_cli_db(cli_app):
    """
    Provide a db object with the structure freshly created. This assumes a clean database.
    It does clean up after itself when it's done (drops everything).
    """
    print("DB FIXTURE")
    # app is an instance of a flask app, _db a SQLAlchemy DB
    from flexmeasures.data import db as _db

    _db.app = cli_app
    with cli_app.app_context():
        _db.create_all()

    yield _db

    print("DB FIXTURE CLEANUP")
    # Explicitly close DB connection
    _db.session.close()

    _db.drop_all()
