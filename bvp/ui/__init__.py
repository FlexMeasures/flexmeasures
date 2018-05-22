from flask import Flask, Blueprint

from flask import send_from_directory

from bvp.utils.time_utils import localized_datetime, naturalized_datetime


# The ui blueprint. It is registered with the Flask app (see app.py)
bvp_ui = Blueprint('bvp_ui', __name__,
                   static_folder='static', static_url_path='/ui/static',
                   template_folder='templates')


def register_at(app: Flask):
    """This can be used to register this blueprint together with other ui-related things"""

    from bvp.ui.crud.assets import AssetCrud
    AssetCrud.register(app)

    import bvp.ui.views  # this is necessary to load the views
    app.register_blueprint(bvp_ui)  # now registering the blueprint will affect all views

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(bvp_ui.static_folder, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

    app.jinja_env.filters['zip'] = zip  # Allow zip function in templates
    app.jinja_env.add_extension('jinja2.ext.do')    # Allow expression statements (e.g. for modifying lists)
    app.jinja_env.filters['localized_datetime'] = localized_datetime
    app.jinja_env.filters['naturalized_datetime'] = naturalized_datetime
