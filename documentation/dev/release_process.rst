Release process
================

This page describes how FlexMeasures releases are cut, and which parts are automated versus manual.
The canonical, most detailed checklist still lives in `FlexMeasures/tsc RELEASE.md <https://github.com/FlexMeasures/tsc/blob/main/RELEASE.md>`_.
This page summarizes that flow and points out where CI now does the mechanical work.

Versioning is derived entirely from git tags via ``hatch-vcs`` (see ``pyproject.toml``'s ``[tool.hatch.version]``), so there is no file where a version string needs to be bumped by hand.

1. Prepare and test (manual)
-----------------------------

* Ensure the corresponding GitHub milestone is complete and the version number choice matches the changes made.
* ``uv sync --group dev --group test`` and ``uv run poe test``.
* For MINOR/MAJOR releases, do manual QA using the Docker Compose stack (tutorials, UI, HEMS client), and write the accompanying blog post.

2. Assemble the changelog (semi-automated)
-------------------------------------------

Run:

.. code-block:: bash

    uv run poe changelog-check

This lists merged PRs since the last tag (via ``ci/list-merged-prs-since-tag.sh``), pre-formatted as changelog bullets.
It is read-only: it does not edit or commit anything.
Review, categorize each entry into *New features* / *Infrastructure / Support* / *Bugfixes*,
and paste them into ``documentation/changelog.rst`` (and ``documentation/cli/change_log.rst`` / ``documentation/api/change_log.rst`` where relevant).

3. Commit, tag, and release (manual — requires GPG signing)
--------------------------------------------------------------

.. code-block:: bash

    git commit -S -sam "changelog updates for v<version>"
    git push
    git tag -s -a v<version> -m ""
    git push --tags

Then create the GitHub Release from the new tag. This step is intentionally manual: GPG signing requires the maintainer's personal key, which cannot be delegated to CI without exporting private key material into repository secrets.

4. Automated publishing (CI)
-------------------------------

Publishing the GitHub Release (step 3) triggers two workflows:

* ``.github/workflows/release.yml`` builds the package and publishes it to PyPI via trusted (OIDC) publishing, then runs a ``pypi-smoke-test`` job that installs the just-published version into a fresh virtual environment and verifies ``flexmeasures.__version__`` matches.
* ``.github/workflows/docker-publish.yml`` builds and pushes the Docker image to Docker Hub, tagged ``lfenergy/flexmeasures:v<version>``, and additionally as ``lfenergy/flexmeasures:latest`` for stable (non-pre-release) releases.

Check the Actions tab for both workflow runs to confirm they succeeded; also spot-check that the new version shows up on `PyPI <https://pypi.org/project/flexmeasures>`_, `Docker Hub <https://hub.docker.com/r/lfenergy/flexmeasures>`_, and that the ReadTheDocs build for the new tag completed.

.. note::
   The ``docker-publish.yml`` workflow can also be re-run manually (``workflow_dispatch``, with a ``tag`` input) if a run needs to be retried.

5. Announce (manual)
----------------------

Publish the blog post (MINOR/MAJOR only), and announce on Mastodon, the mailing list, and the LF Energy Slack.

6. Post-release (manual, MINOR/MAJOR only)
---------------------------------------------

* Start the next development cycle: an empty, signed commit ``Start v<next-version>`` and tag ``v<next-version>.dev0``.
* Update the milestone on GitHub, and add changelog placeholders for upcoming releases.
* Open a dependency-upgrade PR tagged ``dependency-hygiene``.

These are infrequent, low-risk manual steps and involve a judgment call (what the next version number should be), so they are not automated.
