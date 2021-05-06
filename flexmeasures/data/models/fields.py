import click
import marshmallow as ma


class MarshmallowClickMixin(click.ParamType):
    def convert(self, value, param, ctx, **kwargs):
        try:
            return self.deserialize(value, **kwargs)
        except ma.exceptions.ValidationError as e:
            raise click.exceptions.BadParameter(e, ctx=ctx, param=param)
