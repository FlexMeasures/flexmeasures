.. _continuous_integration:

Continuous integration
======================

We run two GitHub Action workflows on each pull request. 
They are designed to only let code through that meets our quality guidelines and (more importantly) is expected not to break things.

You can find their configuration in `.github/workflows`.

Build
-------

This workflow builds the FlexMeasures Docker image and runs the basic toy tutorial in it.

It adds an account and user, creates a battery asset, uploads some price data and then computes a schedule.

Lint and test
--------------

This workflow first lints the code (using Flake8, Black and MyPy).
The configuration for these dev-tools should mirror what developers use (see `.pre-commit-config.yml`), so that there are few surprises when you push code (see also :ref:`developing`).

Then, we actually run the whole test suite (which you would run locally with `make test` or `pytest`).

Only code that passes both of these workflow steps is allowed to be merged.

