from flask.views import MethodView
from marshmallow import ValidationError, validate, validates, fields
from webargs.flaskparser import use_args
from flask_security import login_required, current_user
from flask_json import as_json
from pytz import all_timezones

from flexmeasures.api import ma
from flexmeasures.data.models.user import User as UserModel
from flexmeasures.data.services.users import (
    get_user,
    get_users,
)
from flexmeasures.data.auth_setup import unauthorized_handler
from flexmeasures.api.v2_1 import flexmeasures_api_v2_1

"""
Plan:
1. GET /users using webargs
2. Try using FLask-Smorest
3. Get /users/{id}
4. Other endpoints
5. Make UI use this API
"""

class UserSchema(ma.SQLAlchemySchema):
    class Meta:
        model = UserModel
    
    @validates("timezone")
    def validate_timezone(self, timezone):
        if not timezone in all_timezones:
            raise ValidationError(f"Timezone {timezone} doesn't exist.")
    
    id = ma.auto_field()
    email =ma.auto_field(required=True, validate=validate.Email)
    username = ma.auto_field(required=True)
    active = ma.auto_field()
    timezone = ma.auto_field()
    flexmeasures_roles = ma.auto_field()

 

user_schema = UserSchema()
users_schema = UserSchema(many=True)


@login_required
@flexmeasures_api_v2_1.route("/users")
class Users(MethodView):

    @use_args({"include_inactive": fields.Bool()}, location="query")
    #@as_json
    def get(self, args):
        """List all users.
        Raise if a non-admin tries to use this endpoint.
        """
        if not current_user.has_role("admin"):
            return unauthorized_handler(None, [])
        users = get_users(only_active=args.include_inactive)
        return users_schema.dump(users), 200

'''
@login_required
@check_user()  # TODO
@as_json
def fetch_one(user):
    """Fetch a given user"""
    return user_schema.dump(user), 200
'''