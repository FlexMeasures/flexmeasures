import ast
import inspect
import pkgutil
import importlib
import marshmallow.fields as ma_fields

import flexmeasures


def iter_flexmeasures_modules():
    """Yield all importable flexmeasures modules."""
    prefix = flexmeasures.__name__ + "."
    for modinfo in pkgutil.walk_packages(flexmeasures.__path__, prefix):
        yield importlib.import_module(modinfo.name)


def iter_marshmallow_field_subclasses():
    """Yield (class, module) for Marshmallow Field subclasses."""
    for module in iter_flexmeasures_modules():
        for obj in vars(module).values():
            if (
                inspect.isclass(obj)
                and issubclass(obj, ma_fields.Field)
                and obj is not ma_fields.Field
                and obj.__module__ == module.__name__
            ):
                yield obj, module


def deserialize_calls_super(cls):
    """Return True if _deserialize contains a call to super()._deserialize."""
    try:
        source = inspect.getsource(cls)
    except (OSError, TypeError):
        return True  # skip dynamically defined classes

    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "_deserialize"
                and isinstance(func.value, ast.Call)
                and isinstance(func.value.func, ast.Name)
                and func.value.func.id == "super"
            ):
                return True

    return False


def test_all_custom_fields_call_super_deserialize():
    """
    Ensure that all Marshmallow Field subclasses in FlexMeasures that override
    _deserialize() call super()._deserialize().

    This test statically inspects each class to enforce the invariant that the
    parent Marshmallow Field's deserialization logic is invoked. This is important
    because skipping the call to super()._deserialize() bypasses built-in type
    validation, potentially allowing invalid input to reach downstream code or the
    database.

    Example: flexmeasures.data.schemas.sources.DataSourceIdField overrides
    _deserialize() to fetch a DataSource by ID. If it does not call
    super()._deserialize(), then a non-integer value (e.g., "foo" or "[1, 14]")
    will be passed directly to db.session.get(). This results in a database error
    and a 500 response, instead of a clean validation error, exposing the system
    to unnecessary failures.
    """
    offenders = []
    non_offenders = []

    for cls, module in iter_marshmallow_field_subclasses():
        if "_deserialize" not in cls.__dict__:
            continue  # not overridden

        fqcn = f"{cls.__module__}.{cls.__name__}"
        if deserialize_calls_super(cls):
            non_offenders.append(fqcn)
        else:
            offenders.append(fqcn)

    message_parts = ["Marshmallow Field subclasses overriding _deserialize:\n"]

    if non_offenders:
        message_parts.append(
            "✔ Correct (call super()._deserialize):\n"
            + "\n".join(f"  - {name}" for name in sorted(non_offenders))
        )

    if offenders:
        message_parts.append(
            "✘ Incorrect (missing super()._deserialize):\n"
            + "\n".join(f"  - {name}" for name in sorted(offenders))
        )

    assert not offenders, "\n\n".join(message_parts)
