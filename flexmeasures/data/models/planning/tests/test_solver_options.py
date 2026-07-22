from __future__ import annotations

import pytest

from flexmeasures.data.models.planning.linear_optimization import validate_highs_options

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
