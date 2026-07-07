import inspect
import re
from pathlib import Path

import flexmeasures.data.schemas.scheduling.metadata as metadata_module
from flexmeasures.data.schemas.scheduling.metadata import MetaData


DOC_PATH = Path("documentation/features/scheduling.rst")

# Metadata constants that intentionally do not appear in the documentation
EXCLUDED_METADATA = {
    "RELAX_CAPACITY_CONSTRAINTS",
    "RELAX_SITE_CAPACITY_CONSTRAINTS",
    "RELAX_SOC_CONSTRAINTS",
}


def snake_to_kebab(name: str) -> str:
    return name.lower().replace("_", "-")


def get_metadata_constants():
    """Return all MetaData instances defined in the metadata module."""
    members = inspect.getmembers(metadata_module)
    return {
        name: value
        for name, value in members
        if isinstance(value, MetaData) and name not in EXCLUDED_METADATA
    }


def get_rst_fields():
    """Extract field names from the rst list-table."""
    text = DOC_PATH.read_text()

    # Matches: * - ``field-name``
    pattern = r"\*\s+-\s+``([^`]+)``"
    return set(re.findall(pattern, text))


def test_all_metadata_fields_are_documented():
    metadata_constants = get_metadata_constants()
    documented_fields = get_rst_fields()

    missing = []

    for name in metadata_constants:
        kebab = snake_to_kebab(name)
        if kebab not in documented_fields:
            missing.append((name, kebab))

    assert (
        not missing
    ), "The following MetaData fields are missing from scheduling.rst:\n" + "\n".join(
        f"{name} -> `{kebab}`" for name, kebab in missing
    )
