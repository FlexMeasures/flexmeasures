"""Keep track of which scheduler tests actually run under both backends.

The schedulers build the same model twice — once through Pyomo, once directly in HiGHS —
so a test of scheduler behaviour only means something under one backend if the two agree,
which is the very thing that cannot be assumed.
A module that does not opt into the solver matrix is therefore a coverage hole,
and this test exists so that hole is an explicit, reviewed decision rather than an accident.

To opt a module in, set ``RUN_UNDER_EACH_SOLVER = True`` at its top (see conftest).
"""

from __future__ import annotations

import pathlib

#: Modules that exercise scheduler behaviour but deliberately run under one solver only.
#: Each needs a reason, and the reason should be fixable rather than permanent.
EXEMPT = {
    # These create assets with hardcoded names inline,
    # so running each test twice in one fixture scope violates generic_asset's unique-name constraint.
    # They still pass under the other backend when a whole run is pinned to it with --lp-solver.
    "test_commitments.py": "creates named DB assets; not idempotent across parameters",
    "test_storage.py": "creates named DB assets; not idempotent across parameters",
    "test_process.py": "ProcessScheduler does not use device_scheduler",
    # Covered by the solver matrix through their own fixture instead.
    "test_solver.py": "uses the app_with_each_solver fixture directly",
    "test_highspy_equivalence.py": "runs both backends explicitly, per scenario",
    "test_sign_binaries.py": "introspects the Pyomo model; the highspy path is covered by test_highspy_equivalence",
    "test_solver_options.py": "tests option validation, not scheduling",
    # No scheduling involved.
    "test_device_inventory.py": "no scheduling",
    "test_storage_utils.py": "no scheduling",
    "test_utils.py": "no scheduling",
    "test_utils_fresh_db.py": "no scheduling",
}

TESTS_DIR = pathlib.Path(__file__).parent


def test_scheduler_modules_run_under_each_solver_or_are_exempt():
    """Every planning test module either opts into the solver matrix or is listed as exempt.

    If this fails after adding a module, decide which it is —
    do not add it to EXEMPT just to go green.
    """
    uncovered = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        opts_in = "RUN_UNDER_EACH_SOLVER = True" in path.read_text()
        if not opts_in and path.name not in EXEMPT:
            uncovered.append(path.name)
    assert not uncovered, (
        "These planning test modules run under one solver only, and are not listed as exempt: "
        f"{uncovered}. Either set RUN_UNDER_EACH_SOLVER = True, or add them to EXEMPT with a reason."
    )


def test_exempt_list_has_no_stale_entries():
    """An exempt module that no longer exists, or that has since opted in, should be removed."""
    stale = []
    for name in EXEMPT:
        path = TESTS_DIR / name
        if not path.exists():
            stale.append(f"{name} (gone)")
        elif "RUN_UNDER_EACH_SOLVER = True" in path.read_text():
            stale.append(f"{name} (now opts in)")
    assert not stale, f"Stale EXEMPT entries: {stale}"
