from marshmallow import fields, validate

from flexmeasures.data.schemas.utils import MarshmallowClickMixin


class PercentageFloat(fields.Float, MarshmallowClickMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Insert validation into self.validators so that multiple errors can be stored.
        validator = validate.Range(min=0, max=100)
        self.validators.insert(0, validator)


class NonNegativeFloat(fields.Float, MarshmallowClickMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Insert validation into self.validators so that multiple errors can be stored.
        validator = validate.Range(min=0)
        self.validators.insert(0, validator)
