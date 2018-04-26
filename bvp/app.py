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

app = Flask(__name__)

# Some security measures
install_secret_key(app)
sslify = SSLify(app)

# Gather configuration
read_config(app)
configure_logging(app)
print(app.config)

# Database handling
database.configure_db(app)
migrate = Migrate(app, database.db)

# Setup Flask-Security for user authorization
from bvp.models.user import User, Role, remember_login
user_datastore = SQLAlchemySessionUserDatastore(database.db.session, User, Role)
app.security = Security(app, user_datastore)
user_logged_in.connect(remember_login)
mail = Mail(app)

# Register views
from bvp.views import bvp_views, bvp_error_views
app.register_blueprint(bvp_views)
app.register_blueprint(bvp_error_views)

from bvp.crud.assets import AssetCrud
AssetCrud.register(app)


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')


app.jinja_env.add_extension('jinja2.ext.do')    # Allow expression statements in templates (e.g. for modifying lists)
app.jinja_env.filters['zip'] = zip  # Allow zip function in templates
app.jinja_env.filters['localized_datetime'] = localized_datetime
app.jinja_env.filters['naturalized_datetime'] = naturalized_datetime


# Register some useful custom scripts with the flask cli

# @app.before_first_request
@app.cli.command()
def populate_db_structure():
    """Initialize the database."""
    from bvp.scripts import db_handling
    click.echo('Populating the database structure ...')
    db_handling.populate_structure(app)


@app.cli.command()
def depopulate_db_structure():
    """Initialize the database."""
    from bvp.scripts import db_handling
    click.echo('Depopulating the database structure ...')
    db_handling.depopulate_structure(app)