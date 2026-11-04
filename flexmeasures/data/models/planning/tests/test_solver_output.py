"""An appsi solver's console output stays out of the application's log handlers (#2742).

Pyomo's appsi solvers drain what the solver prints into a logger that propagates to the root by default,
from inside a capture that points file descriptors 1 and 2 at a pipe.
A console handler then writes each line back into that pipe:
it comes back round with one more prefix, and once a line no longer fits in the pipe, the worker hangs.
The solves run in a subprocess, because the capture redirects the process's own file descriptors.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import flexmeasures

highspy = pytest.importorskip("highspy")

#: A console handler on stdout, as FlexMeasures installs one, then a handful of small appsi_highs schedules.
#: The handler's format makes a re-captured line recognisable: it carries the prefix twice.
#: At DEBUG, FlexMeasures lets HiGHS print its full log, so each solve has plenty of lines to re-capture.
SOLVES = textwrap.dedent("""
    import logging, sys
    from flask import Flask
    from flexmeasures.data.models.planning.tests.test_solver_options import solve_a_tiny_schedule

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("APP: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    app = Flask("solver-output")
    app.config["FLEXMEASURES_LP_SOLVER"] = "appsi_highs"
    app.logger.setLevel(logging.DEBUG)
    with app.app_context():
        for _ in range(5):
            solve_a_tiny_schedule()
    print("solved")
    """)


def test_the_solver_output_is_not_relogged_through_the_console_handler():
    """No line comes back round through the console handler, yet the solver's log is still shown, once per solve."""
    # Import this checkout of FlexMeasures in the subprocess, whichever one is installed.
    pythonpath = os.pathsep.join(
        filter(
            None,
            [str(Path(flexmeasures.__file__).parents[1]), os.environ.get("PYTHONPATH")],
        )
    )
    solves = subprocess.run(
        [sys.executable, "-c", SOLVES],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": pythonpath},
    )
    output = solves.stdout + solves.stderr

    assert solves.returncode == 0, output[-2000:]
    assert "solved" in solves.stdout
    assert "APP: APP:" not in output, output[:2000]
    # Shown rather than dropped: the banner HiGHS prints once per solve reaches the console exactly that often.
    assert output.count("Running HiGHS") == 5, output[:2000]
