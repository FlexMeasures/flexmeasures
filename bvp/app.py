import os

from flask import Flask
from flask import send_from_directory
from flask_mail import Mail
from flask_sslify import SSLify
from flask_migrate import Migrate
from flask_security import Security, SQLAlchemySessionUserDatastore
from flask_login import user_logged_in
import click

import bvp.database as database
from bvp.utils import install_secret_key
from bvp.utils.config_utils import read_config, configure_logging
from bvp.utils.time_utils import localized_datetime, naturalized_datetime


"""
Prepare the Flask application object, configure logger and session.
"""


def create_app(environment=None):
    """
    Create a Flask app and configure it.
    The environment name is usually gotten from environment variable (BVP_ENVIRONMENT), but can be overwritten here
    (e.g. fore teting).
    """
    new_app = Flask(__name__)

    # Some basic security measures

    install_secret_key(new_app)
    sslify = SSLify(new_app)

    # Configuration

    read_config(new_app, environment=environment)
    configure_logging(new_app)
    print(new_app.config)

    # Database handling

    database.configure_db(new_app)
    migrate = Migrate(new_app, database.db)

    # Setup Flask-Security for user authentication & authorization

    from bvp.models.user import User, Role, remember_login
    user_datastore = SQLAlchemySessionUserDatastore(database.db.session, User, Role)
    new_app.security = Security(new_app, user_datastore)
    user_logged_in.connect(remember_login)
    mail = Mail(new_app)

    # Register the UI

    from bvp.ui.views import bvp_ui
    new_app.register_blueprint(bvp_ui)

    from bvp.ui.crud.assets import AssetCrud
    AssetCrud.register(new_app)

    @new_app.route('/favicon.ico')
    def favicon():
        return send_from_directory(bvp_ui.static_folder, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

    new_app.jinja_env.filters['zip'] = zip  # Allow zip function in templates
    new_app.jinja_env.add_extension('jinja2.ext.do')    # Allow expression statements (e.g. for modifying lists)
    new_app.jinja_env.filters['localized_datetime'] = localized_datetime
    new_app.jinja_env.filters['naturalized_datetime'] = naturalized_datetime

    # Register some useful custom scripts with the flask cli

    # @new_app.before_first_request
    @new_app.cli.command()
    def populate_db_structure():
        """Initialize the database."""
        from bvp.scripts import db_handling
        click.echo('Populating the database structure ...')
        db_handling.populate_structure(new_app)

    @new_app.cli.command()
    def depopulate_db_structure():
        """Initialize the database."""
        from bvp.scripts import db_handling
        click.echo('Depopulating the database structure ...')
        db_handling.depopulate_structure(new_app)

    return new_app


app = create_app()