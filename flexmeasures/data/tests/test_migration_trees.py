"""Tests on the two Alembic revision trees themselves."""

from __future__ import annotations

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
import pytest

from flexmeasures.data.utils import (
    LEGACY_HEAD,
    MIGRATIONS_DIR,
    SQUASH_BASELINE,
    VERSIONS_CURRENT_DIR,
    VERSIONS_LEGACY_DIR,
    _read_revision_id,
    get_current_tree_head,
    get_current_tree_revisions,
)


def script_directory_for(version_locations) -> ScriptDirectory:
    config = AlembicConfig()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("path_separator", "os")
    config.set_main_option("version_locations", str(version_locations))
    return ScriptDirectory.from_config(config)


def test_current_tree_head_read_from_filenames_matches_alembic():
    """The head derived from filename order must be the head Alembic computes topologically.

    Filename order and topological order can diverge in two ways,
    and this catches both:
    a branch or merge in the tree gives Alembic more than one head,
    and a backdated or clock-skewed filename puts the wrong file last.
    """
    script = script_directory_for(VERSIONS_CURRENT_DIR)

    assert len(script.get_heads()) == 1, (
        "The current revision tree must have exactly one head, "
        f"but Alembic found {script.get_heads()}."
    )
    assert script.get_heads()[0] == get_current_tree_head(), (
        "The head read from the last filename is not the head Alembic computes. "
        "Check that the new revision's filename timestamp sorts last."
    )


def test_current_tree_has_a_single_root_which_is_the_baseline():
    """The current tree is an independent root, deliberately disconnected from the legacy tree."""
    script = script_directory_for(VERSIONS_CURRENT_DIR)
    roots = [
        revision.revision
        for revision in script.walk_revisions()
        if revision.down_revision is None
    ]

    assert roots == [SQUASH_BASELINE]


def test_legacy_tree_is_frozen_at_its_known_head():
    """The legacy tree never gains a revision, so its head stays the literal in `utils.py`."""
    script = script_directory_for(VERSIONS_LEGACY_DIR)

    assert list(script.get_heads()) == [LEGACY_HEAD]


def test_the_two_trees_share_no_revision():
    """A revision id in both trees would make `alembic_version` ambiguous across the cut."""
    legacy_revisions = {
        _read_revision_id(path)
        for path in VERSIONS_LEGACY_DIR.glob("*.py")
        if not path.name.startswith("__")
    }

    assert not legacy_revisions & get_current_tree_revisions()


def test_baseline_refuses_to_downgrade():
    """Downgrading across the squash cut has to fail loudly, rather than silently doing the wrong thing."""
    script = script_directory_for(VERSIONS_CURRENT_DIR)
    baseline = script.get_revision(SQUASH_BASELINE)

    with pytest.raises(
        NotImplementedError, match="Cannot downgrade past the squash baseline"
    ):
        baseline.module.downgrade()
