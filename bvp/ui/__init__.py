from flask import Blueprint

# The ui blueprint. It is registered with the Flask app (see app.py)
bvp_ui = Blueprint('bvp_ui', __name__, static_folder='static', static_url_path='/ui/static', template_folder='templates')
