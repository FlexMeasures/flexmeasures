from functools import wraps

from flask import current_app, abort
from flask_json import as_json

from flexmeasures.data.models.user import User as UserModel
from flexmeasures.api.common.responses import required_info_missing

"""
Decorator factories to load objects from ID parameters.
"""


def load_user():
    """Decorator which loads a user by the id expected in the path.
    Raises 400 if that is not possible due to wrong parameters.
    Raises 404 if user is not found.
    Example:

        @app.route('/user/<id>')
        @check_user
        def get_user(user):
            return user_schema.dump(user), 200

    The route must specify one parameter ― id.

    TODO:
    - support parameters in query (see load_account)?
    - return current_user if no ID is given?
    """

    def wrapper(fn):
        @wraps(fn)
        @as_json
        def decorated_endpoint(*args, **kwargs):

            args = list(args)
            if len(args) == 0:
                current_app.logger.warning("Request missing id.")
                return required_info_missing(["id"])

            try:
                id = int(args[0])
                args = args[1:]
            except ValueError:
                current_app.logger.warning("Cannot parse ID argument from request.")
                return required_info_missing(["id"], "Cannot parse ID arg as int.")

            user: UserModel = UserModel.query.filter_by(id=int(id)).one_or_none()

            if user is None:
                raise abort(404, f"User {id} not found")

            return fn(user, *args, **kwargs)

        return decorated_endpoint

    return wrapper
