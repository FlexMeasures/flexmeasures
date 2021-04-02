from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import MetaData
import sqlalchemy as sa
from flask_sqlalchemy import SQLAlchemy
from flask import Flask

from flexmeasures.data.models import naming_convention


db: sa = None  # typed attributes unavailable in flask-sqlalchemy, see https://github.com/pallets/flask-sqlalchemy/issues/867
Base = None  # type: ignore
session_options = None


def init_db():
    """Initialise the database object"""
    global db, Base, session_options
    db = SQLAlchemy(
        session_options=session_options,
        metadata=MetaData(naming_convention=naming_convention),
    )
    Base = declarative_base(metadata=db.metadata)
    Base.query = None


def configure_db_for(app: Flask):
    """Call this to configure the database and the tools we use on it for the Flask app.
    This should only be called once in the app's lifetime."""
    global db, Base

    with app.app_context():
        db.init_app(app)
        app.db = db

        Base.query = db.session.query_property()

        # Import all modules here that might define models so that
        # they will be registered properly on the metadata. Otherwise
        # you will have to import them first before calling configure_db().
        from flexmeasures.data.models import (  # noqa: F401
            time_series,
            markets,
            assets,
            weather,
            data_sources,
            user,
            task_runs,
            forecasting,
        )  # noqa: F401

        # This would create db structure based on models, but you should use `flask db upgrade` for that.
        # Base.metadata.create_all(bind=db.engine)


def commit_and_start_new_session(app: Flask):
    """Use this when a script wants to save a state before continuing
    Not tested well, just a starting point - not recommended anyway for any logic used by views or tasks.
    Maybe session.flush can help you there."""
    global db, Base, session_options
    db.session.commit()
    db.session.close()
    db.session.remove()
    db.session = db.create_scoped_session(options=session_options)
    Base.query = db.session.query_property()
    from flask_security import SQLAlchemySessionUserDatastore
    from flexmeasures.data.models.user import User, Role

    app.security.datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)


init_db()  # This makes sure this module can be imported from right away
