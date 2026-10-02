"""Tests that the explicit registry lists every built-in data generator, by walking the package and comparing."""

import pytest

from flexmeasures import Forecaster, Reporter, Scheduler
from flexmeasures.data.models.registry import BUILTIN_DATA_GENERATORS
from flexmeasures.utils.coding_utils import get_classes_module, load_classes

#: Classes that a walk of the package finds, but which are deliberately not registered.
#: These are intermediate base classes: they satisfy the interface without being an implementation a user can pick.
#: Adding a name here is a decision about public surface, so it should be argued for in review.
NOT_REGISTERED = {
    "scheduler": {"MetaStorageScheduler"},
    "reporter": set(),
    "forecaster": set(),
}

GENERATOR_TYPES = [
    ("forecaster", Forecaster),
    ("reporter", Reporter),
    ("scheduler", Scheduler),
]


@pytest.mark.parametrize("generator_type, superclass", GENERATOR_TYPES)
def test_every_data_generator_is_declared_or_deliberately_excluded(
    generator_type, superclass
):
    """No data generator may be missed by accident.

    Every subclass found by walking flexmeasures.data.models must either be declared in the registry,
    or be named in NOT_REGISTERED as a deliberate exclusion.
    """
    found = set(get_classes_module("flexmeasures.data.models", superclass))
    declared = set(load_classes(BUILTIN_DATA_GENERATORS[generator_type], superclass))
    undeclared = found - declared - NOT_REGISTERED[generator_type]
    assert not undeclared, (
        f"{sorted(undeclared)} subclass {superclass.__name__} but are not declared in BUILTIN_DATA_GENERATORS"
        f" nor listed as a deliberate exclusion in NOT_REGISTERED."
    )


@pytest.mark.parametrize("generator_type, superclass", GENERATOR_TYPES)
def test_declared_data_generators_all_exist(generator_type, superclass):
    """Every declared spec must resolve, so that a typo or a moved class fails here rather than at start-up."""
    declared = load_classes(BUILTIN_DATA_GENERATORS[generator_type], superclass)
    assert declared, f"No built-in {generator_type} is declared."
    for klass in declared.values():
        assert issubclass(klass, superclass)
        assert klass is not superclass


def test_excluded_classes_still_exist():
    """A name in NOT_REGISTERED should describe reality.

    If an excluded class is renamed or deleted, the exclusion is stale and should go, so that it cannot quietly
    mask a genuinely undeclared data generator later.
    """
    for generator_type, superclass in GENERATOR_TYPES:
        found = set(get_classes_module("flexmeasures.data.models", superclass))
        stale = NOT_REGISTERED[generator_type] - found
        assert (
            not stale
        ), f"NOT_REGISTERED[{generator_type!r}] names {sorted(stale)}, which no longer exist."


def test_registered_data_generators_are_reachable_by_name(app):
    """The registry is keyed by class name, because that is what users and DataSource rows refer to."""
    for generator_type, _ in GENERATOR_TYPES:
        for name, klass in app.data_generators[generator_type].items():
            assert klass.__name__ == name
