from sqlalchemy.ext.declarative import declarative_base
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
Base = declarative_base()
Base.query = None
session = None


def configure_db(app):
    """Call this to configure the database and the tools we use on it."""
    global db, Base, session

    with app.app_context():
        db.init_app(app)
        app.db = db

        Base.query = db.session.query_property()

        # Import all modules here that might define models so that
        # they will be registered properly on the metadata. Otherwise
        # you will have to import them first before calling configure_db().
        from bvp.data.models import (
            assets,
            markets,
            weather,
            user,
            task_runs,
        )  # noqa: F401

        Base.metadata.create_all(bind=db.engine)
