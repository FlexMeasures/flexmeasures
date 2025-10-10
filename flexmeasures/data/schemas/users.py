from marshmallow import validates, ValidationError, validate
from pytz import all_timezones

from flexmeasures.data import db, ma
from flexmeasures.data.models.user import User as UserModel
from flexmeasures.data.schemas.times import AwareDateTimeField


class SQLAlchemySchema(ma.SQLAlchemySchema):
    """Workaround from https://github.com/marshmallow-code/flask-marshmallow/issues/44#issuecomment-1002740778"""

    class Meta(ma.SQLAlchemySchema.Meta):
        sqla_session = db.session


class UserSchema(SQLAlchemySchema):
    """
    This schema lists fields we support through this API (e.g. no password).
    """

    class Meta(SQLAlchemySchema.Meta):
        model = UserModel

    @validates("timezone")
    def validate_timezone(self, timezone, **kwargs):
        if timezone not in all_timezones:
            raise ValidationError(f"Timezone {timezone} doesn't exist.")

    id = ma.auto_field(dump_only=True)
    email = ma.auto_field(required=True, validate=validate.Email())
    username = ma.auto_field(required=True)
    account_id = ma.auto_field(dump_only=True)
    active = ma.auto_field()
    timezone = ma.auto_field()
    flexmeasures_roles = ma.auto_field()
    last_login_at = AwareDateTimeField()
    last_seen_at = AwareDateTimeField()
