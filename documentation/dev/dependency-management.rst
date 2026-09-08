.. _dependency_management:

Dependency Management
=======================

Requirements
-------------

FlexMeasures is built on the shoulder of giants, namely other open source libraries.
Look into the ``pyproject.toml`` file to see what is required to run FlexMeasures or to test it, or to build this documentation.

The ``pyproject.toml`` file specifies our general demands, and in the ``uv.lock`` file, we keep a set of pinned dependency versions, so we can all work on the same background (crucial to compare behavior of installations to each other).

We use the excellent `uv <https://docs.astral.sh/uv/>`_ tool to manage our dependencies.
First, `install uv <https://docs.astral.sh/uv/getting-started/installation/>`_, then pin it to the version this project requires:

.. code-block:: bash

    $ uv self update 0.12.7

We enforce this exact version through ``[tool.uv].required-version`` in ``pyproject.toml``, so that lockfile output is reproducible between contributors and CI.
``uv`` refuses to run at all on a version mismatch, so you will notice right away.

.. note:: ``uv self update`` only works if you installed ``uv`` with its standalone installer.
          If you installed it with ``pip`` or ``brew``, pin it there instead (e.g. ``pip install uv==0.12.7``).

Now install the dependencies:

.. code-block:: bash

    $ uv sync --group dev --group test

To upgrade the dependencies to the latest compatible versions, we can run:

.. code-block:: bash

    $ uv lock --upgrade

Upgrading ``uv`` itself is a deliberate step, which we take in the periodic ``chore: upgrade all dependencies`` PR.
Because ``required-version`` gates every ``uv`` invocation, and not just ``uv lock``, all the places where we pin ``uv`` have to move together, in one reviewed change:

- ``[tool.uv].required-version`` in ``pyproject.toml``
- the ``version`` input of ``astral-sh/setup-uv`` in ``.github/workflows/lint-and-test.yml``, ``.github/workflows/docker-build.yml``, ``.github/workflows/docker-qa.yml``, ``.github/workflows/pypi-publish.yml`` and ``.github/actions/setup-test-env/action.yml``
- ``ARG UV_VERSION`` in the ``Dockerfile`` (which selects the ``ghcr.io/astral-sh/uv`` base image)
- the ``asdf`` commands under ``pre_create_environment`` in ``.readthedocs.yaml``

Miss one, and that build fails rather than only producing a noisy lockfile.

Python versions
----------------

In addition, we support a range of Python versions (as you can see in the ``requires-python`` field in ``pyproject.toml``).

Development generally happens on one specific Python version, namely the one specified in the ``python.version`` file.

Still, we'd also like to be able to test FlexMeasures across all these versions.
We've added that capability to our CI pipeline (GitHub Actions), so you could clone it and make a PR, in order to run them.
