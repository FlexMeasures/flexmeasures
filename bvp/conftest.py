import pytest

from flask_security import SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password

from bvp.app import create as create_app

"""
Useful things for all tests.

One application is made per test session, but cleanup and recreation currently happens per test.
This can be sped up if needed by moving some functions to "module" or even "session" scope,
but then the tests need to share data and and data modifcations can lead to tricky debugging.
"""


@pytest.fixture(scope="session")
def app():
    print("APP FIXTURE")
    test_app = create_app(env="testing")

    # Establish an application context before running the tests.
    ctx = test_app.app_context()
    ctx.push()

    yield test_app

    ctx.pop()

    print("DONE WITH APP FIXTURE")


@pytest.fixture(scope="function")
def db(app):
    """
    Provide a db object with the structure freshly created. This assumes a clean database.
    It does clean up after itself when it's done (drops everything).
    """
    print("DB FIXTURE")
    # app is an instance of a flask app, _db a SQLAlchemy DB
    from bvp.data.config import db as _db

    _db.app = app
    with app.app_context():
        _db.create_all()

    yield _db

    print("DB FIXTURE CLEANUP")
    # Explicitly close DB connection
    _db.session.close()

    _db.drop_all()


@pytest.fixture(scope="function")
def setup_roles_users(db):
    """Create a minimal set of roles and users"""
    from bvp.data.models.user import User, Role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    test_prosumer_role = user_datastore.create_role(
        name="prosumer", description="A prosumer."
    )
    test_prosumer = user_datastore.create_user(
        username="Test Prosumer",
        email="test_prosumer@seita.nl",
        password=hash_password("testtest"),
    )
    user_datastore.add_role_to_user(test_prosumer, test_prosumer_role)


@pytest.fixture(scope="function", autouse=True)
def setup_assets(db, setup_roles_users):
    """Make some asset types and add assets to known test users."""
    from bvp.data.models.assets import AssetType, Asset
    from bvp.data.models.user import User, Role

    db.session.add(
        AssetType(
            name="solar",
            is_producer=True,
            can_curtail=True,
            daily_seasonality=True,
            yearly_seasonality=True,
        )
    )
    db.session.add(
        AssetType(
            name="wind",
            is_producer=True,
            can_curtail=True,
            daily_seasonality=True,
            yearly_seasonality=True,
        )
    )

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    test_prosumer = user_datastore.find_user(email="test_prosumer@seita.nl")

    for asset_name in ["wind-asset-1", "wind-asset-2", "solar-asset-1"]:
        asset = Asset(
            name=asset_name,
            asset_type_name="wind" if "wind" in asset_name else "solar",
            capacity_in_mw=1,
            latitude=100,
            longitude=100,
        )
        asset.owner = test_prosumer
        db.session.add(asset)
