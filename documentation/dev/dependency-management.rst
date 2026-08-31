Dependency Management
=======================

Requirements
-------------

FlexMeasures is built on the shoulder of giants, namely other open source libraries.
Look into the ``pyproject.toml`` file to see what is required to run FlexMeasures or to test it, or to build this documentation.

The ``pyproject.toml`` file specifies our general demands, and in the ``uv.lock`` file, we keep a set of pinned dependency versions, so we can all work on the same background (crucial to compare behavior of installations to each other).

We use the excellent `uv <https://docs.astral.sh/uv/>`_ tool to manage our dependencies.
First, `install uv <https://docs.astral.sh/uv/getting-started/installation/>`_, then run:

.. code-block:: bash

    $ uv self update 0.10.9

FlexMeasures enforces this exact ``uv`` version via ``[tool.uv].required-version`` in ``pyproject.toml`` to keep lockfile output reproducible between contributors and CI.

.. code-block:: bash

    $ uv sync --group dev --group test

To upgrade the dependencies to the latest compatible versions, we can run:

.. code-block:: bash

    $ uv lock --upgrade

Upgrading ``uv`` itself is a deliberate step in the periodic ``chore: upgrade all dependencies`` PR: bump ``[tool.uv].required-version`` and the ``astral-sh/setup-uv`` workflow pins together in one reviewed change.

Python versions
----------------

In addition, we support a range of Python versions (as you can see in the ``requires-python`` field in ``pyproject.toml``).

Development generally happens on one specific Python version, namely the one specified in the ``python.version`` file.

Still, we'd also like to be able to test FlexMeasures across all these versions.
We've added that capability to our CI pipeline (GitHub Actions), so you could clone it and make a PR, in order to run them.
