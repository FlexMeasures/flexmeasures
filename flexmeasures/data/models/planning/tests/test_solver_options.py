from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd
import pytest

from flexmeasures.data.models.planning.linear_optimization import (
    device_scheduler,
    validate_highs_options,
)
from flexmeasures.data.models.planning.scheduling_problem import solver_options
from flexmeasures.data.models.planning.utils import initialize_df

highspy = pytest.importorskip("highspy")


def highs_accepts(name, value) -> bool:
    probe = highspy.Highs()
    probe.setOptionValue("output_flag", False)
    return probe.setOptionValue(name, value) == highspy.HighsStatus.kOk


def test_validate_highs_options_accepts_the_defaults_we_ship():
    """The profile device_scheduler applies itself must stay acceptable to HiGHS."""
    validate_highs_options(
        {
            "mip_rel_gap": "0",
            "mip_abs_gap": "0",
            "primal_feasibility_tolerance": "1e-9",
            "dual_feasibility_tolerance": "1e-9",
            "mip_feasibility_tolerance": "1e-9",
            "output_flag": "false",
        }
    )


def test_validate_highs_options_rejects_unknown_option_name():
    with pytest.raises(ValueError, match="no_such_option"):
        validate_highs_options({"no_such_option": "1"})


def test_validate_highs_options_rejects_invalid_option_value():
    with pytest.raises(ValueError, match="solver='banana'"):
        validate_highs_options({"solver": "banana"})


def test_validate_highs_options_reports_every_rejected_option():
    with pytest.raises(ValueError) as exc:
        validate_highs_options({"no_such_option": "1", "solver": "banana"})
    assert "no_such_option" in str(exc.value)
    assert "solver='banana'" in str(exc.value)


def test_validate_highs_options_rejects_solver_missing_from_this_build():
    """HiPO needs a HiGHS built against BLAS and METIS; the pip-installed one is not.

    Pyomo's appsi_highs would swallow this, so we must not.
    """
    if highs_accepts("solver", "hipo"):
        pytest.skip("this HiGHS build provides the HiPO solver")
    with pytest.raises(ValueError, match="hipo"):
        validate_highs_options({"solver": "hipo"})


def test_validate_highs_options_warns_about_the_global_thread_scheduler(app, caplog):
    """HiGHS initializes its thread scheduler once per process, so `threads` is a trap."""
    with app.app_context():
        validate_highs_options({"threads": 2})
    assert "thread scheduler" in caplog.text


@pytest.fixture
def app_logging_level(app):
    """Set the app logger's level for one test, as LOGGING_LEVEL would, and restore it afterwards."""
    original_level = app.logger.level

    def set_level(level: int | str):
        app.logger.setLevel(level)

    yield set_level
    app.logger.setLevel(original_level)


@pytest.mark.parametrize(
    "level, silenced",
    [
        (logging.ERROR, True),
        (logging.WARNING, True),
        (logging.INFO, True),
        ("INFO", True),
        (logging.DEBUG, False),
        ("DEBUG", False),
    ],
)
def test_highs_output_is_silenced_unless_debugging(
    app, app_logging_level, level, silenced
):
    """HiGHS logs to the console, bypassing our loggers, so only DEBUG lets it through.

    LOGGING_LEVEL may be configured as a name or as a number; both must be honoured.
    """
    app_logging_level(level)
    with app.app_context():
        options = solver_options("highspy")
    assert (options.get("output_flag") == "false") is silenced


def solve_a_tiny_schedule():
    columns = [
        "equals",
        "max",
        "min",
        "efficiency",
        "derivative equals",
        "derivative max",
        "derivative min",
        "derivative down efficiency",
        "derivative up efficiency",
        "stock delta",
    ]
    start = pd.Timestamp("2020-01-01T00:00:00+01:00")
    end = pd.Timestamp("2020-01-01T02:00:00+01:00")
    device_constraints = initialize_df(columns, start, end, timedelta(hours=1))
    device_constraints["derivative max"] = 1
    device_constraints["derivative min"] = -1
    _, _, results, _ = device_scheduler(
        device_constraints=[device_constraints],
        ems_constraints=initialize_df(columns, start, end, timedelta(hours=1)),
        commitment_quantities=[pd.Series(0, index=device_constraints.index)],
        commitment_downwards_deviation_price=[
            pd.Series(-1, index=device_constraints.index)
        ],
        commitment_upwards_deviation_price=[
            pd.Series(1, index=device_constraints.index)
        ],
    )
    assert results.solver.termination_condition == "optimal"


def test_highspy_writes_nothing_to_the_console_outside_debug(
    app, app_logging_level, monkeypatch, capfd
):
    """Not even the banner HiGHS prints when its model is first built.

    HiGHS writes to the process's stdout directly, so this captures at the file-descriptor level.
    """
    monkeypatch.setitem(app.config, "FLEXMEASURES_LP_SOLVER", "highspy")
    app_logging_level(logging.INFO)
    capfd.readouterr()  # discard anything printed before the solve
    with app.app_context():
        solve_a_tiny_schedule()
    out, err = capfd.readouterr()
    assert "HiGHS" not in out + err
    assert out == ""


def test_highspy_writes_its_log_to_the_console_when_debugging(
    app, app_logging_level, monkeypatch, capfd
):
    """The counterpart of the test above, so that one cannot pass merely because nothing is captured."""
    monkeypatch.setitem(app.config, "FLEXMEASURES_LP_SOLVER", "highspy")
    app_logging_level(logging.DEBUG)
    capfd.readouterr()
    with app.app_context():
        solve_a_tiny_schedule()
    out, _ = capfd.readouterr()
    assert "Running HiGHS" in out
