.. _developing:



Developing for FlexMeasures
===========================

This page instructs developers who work on FlexMeasures how to set up the development environment.
Furthermore, we discuss several guidelines and best practices.

.. contents:: Table of contents
    :local:
    :depth: 1

|
.. note:: Are you implementing code based on FlexMeasures, you're probably interested in :ref:`datamodel`.


Getting started
------------------

Virtual environment
^^^^^^^^^^^^^^^^^^^^

Using a virtual environment is best practice for Python developers. We also strongly recommend using a dedicated one for your work on FlexMeasures, as our make target (see below) will use ``pip-sync`` to install dependencies, which could interfere with some libraries you already have installed.


* Make a virtual environment: ``python3.10 -m venv flexmeasures-venv`` or use a different tool like ``mkvirtualenv`` or virtualenvwrapper. You can also use
  an `Anaconda distribution <https://conda.io/docs/user-guide/tasks/manage-environments.html>`_ as base with ``conda create -n flexmeasures-venv python=3.10``.
* Activate it, e.g.: ``source flexmeasures-venv/bin/activate``


Download FlexMeasures
^^^^^^^^^^^^^^^^^^^^^^^
Clone the `FlexMeasures repository <https://github.com/FlexMeasures/flexmeasures.git>`_ from GitHub.

.. code-block:: bash

   $ git clone https://github.com/FlexMeasures/flexmeasures.git


Dependencies
^^^^^^^^^^^^^^^^^^^^

Go into the ``flexmeasures`` folder and install all dependencies including the ones needed for development:

.. code-block:: bash

   $ cd flexmeasures
   $ make install-for-dev

:ref:`Install the LP solver <install-lp-solver>`. On Linux, the HiGHS solver can be installed with:

.. code-block:: bash

   $ pip install highspy

On MacOS it will be installed locally by `make install-for-test` and no actions are required on your part

Besides highs, the CBC solver is required for tests as well:

.. tabs::

    .. tab:: Linux

        .. code-block:: bash

            $ apt-get install coinor-cbc

    .. tab:: MacOS

        .. code-block:: bash

            $ brew install cbc


Configuration
^^^^^^^^^^^^^^^^^^^^

Most configuration happens in a config file, see :ref:`configuration` on where it can live and all supported settings.

For now, we let it live in your home directory and we add the first required setting: a secret key:

.. code-block:: bash

   echo "SECRET_KEY=\"`python3 -c 'import secrets; print(secrets.token_hex(24))'`\"" >> ~/.flexmeasures.cfg

   
Also, we add some env settings in an `.env` file. Create that file in the `flexmeasures` directory (from where you'll run flexmeasures) and enter:

.. code-block:: bash

    FLEXMEASURES_ENV="development"
    LOGGING_LEVEL="INFO"

The development mode makes sure we don't need SSL to connect, among other things. 


Database
^^^^^^^^^^^^^^^^

See :ref:`host-data` for tips on how to install and upgrade databases (postgres and redis).


Loading data
^^^^^^^^^^^^^^^^^^^^

If you have a SQL Dump file, you can load that:

.. code-block:: bash

    $ psql -U {user_name} -h {host_name} -d {database_name} -f {file_path}

One other possibility is to add a toy account (which owns some assets and a battery):

.. code-block:: bash

    $ flexmeasures add toy-account



Run locally
^^^^^^^^^^^^^^^^^^^^

Now, to start the web application, you can run:

.. code-block:: bash

    $ flexmeasures run


Or:

.. code-block:: bash

    $ python run-local.py


And access the server at http://localhost:5000

If you added a toy account, you could log in with `toy-user@flexmeasures.io`, password `toy-password`.

Otherwise, you need to add some other user first. Here is how we add an admin:

.. code-block:: bash
    
    $ flexmeasures add account --name MyCompany
    $ flexmeasures add user --username admin --account 1 --email admin@mycompany.io --roles admin

(The `account` you need in the 2nd command is printed by the 1st)


.. include:: ../notes/macOS-port-note.rst

.. note::

    If you are on Windows, then running & developing FlexMeasures will not work 100%. For instance, the queueing only works if you install rq-win (https://github.com/michaelbrooks/rq-win) manually and the make tooling is difficult to get to work as well.
    We recommend to use the Windows Sub-system for Linux (https://learn.microsoft.com/en-us/windows/wsl/install) or work via Docker-compose (https://flexmeasures.readthedocs.io/en/latest/dev/docker-compose.html).



Logfile
--------

FlexMeasures logs to a file called ``flexmeasures.log``. You'll find this in the application's context folder, e.g. where you called ``flexmeasures run``.

A rolling log file handler is used, so if ``flexmeasures.log`` gets to a few megabytes in size, it is copied to `flexmeasures.log.1` and the original file starts over empty again. 

The default logging level is ``WARNING``. To see more, you can update this with the config setting ``LOGGING_LEVEL``, e.g. to ``INFO`` or ``DEBUG``


Mocking an Email Server for Development
--------------------------------

To handle emails locally during development, you can use MailHog. Follow these steps to set it up:

.. code-block:: bash

   $ docker run -p 8025:8025 -p 1025:1025 --name mailhog mailhog/mailhog
   $ export MAIL_PORT=1025  # You can also add this to your local flexmeasures.cfg

Now, emails (e.g., password-reset) are being sent via this local server. Go to http://localhost:8025 to see all sent emails in a web UI.

Tests
-----

You can run automated tests with:

.. code-block:: bash

    $ make test


which behind the curtains installs dependencies and calls ``pytest``.

However, a test database (postgres) is needed to run these tests. If you have postgres, here is the short version on how to add the test database:

.. code-block:: bash

    $ make clean-db db_name=flexmeasures_test db_user=flexmeasures_test
    $ # the password for the db user is "flexmeasures_test"

.. note:: The section :ref:`host-data` has more details on using postgres for FlexMeasures.

Alternatively, if you don't feel like installing postgres for the time being, here is a docker command to provide a test database:

.. code-block:: bash

    $ docker run --rm --name flexmeasures-test-db -e POSTGRES_PASSWORD=flexmeasures_test -e POSTGRES_DB=flexmeasures_test -e POSTGRES_USER=flexmeasures_test -p 5432:5432 -v ./ci/load-psql-extensions.sql:/docker-entrypoint-initdb.d/load-psql-extensions.sql -d postgres:latest

.. warning:: This assumes that the port 5432 is not being used on your machine (for instance by an existing postgres database service).

If you want the tests to create a coverage report (printed on the terminal), you can run the ``pytest`` command like this:

.. code-block:: bash

   $ pytest --cov=flexmeasures --cov-config .coveragerc

You can add `--cov-report=html`, after which a file called `htmlcov/index.html` is generated.
Or, after a test run with coverage turned on as shown above, you can still generate it in another form:

.. code-block:: bash

    $ python3 -m coverage [html|lcov|json]



Versioning
----------

We use `setuptool_scm <https://github.com/pypa/setuptools_scm/>`_ for versioning, which bases the FlexMeasures version on the latest git tag and the commits since then.

So as a developer, it's crucial to use git tags for versions only.

We use semantic versioning, and we always include the patch version, not only max and min, so that setuptools_scm makes the correct guess about the next minor version. Thus, we should use ``2.0.0`` instead of ``2.0``.

See ``to_pypi.sh`` for more commentary on the development versions.

Our API has its own version, which moves much slower. This is important to explicitly support outside apps who were coded against older versions. 


Auto-applying formatting and code style suggestions
-----------------------------------------------------

We use `Black <https://github.com/ambv/black>`_ to format our Python code and `Flake8 <https://flake8.pycqa.org>`_ to enforce the PEP8 style guide and linting.
We also run `mypy <http://mypy-lang.org/>`_ on many files to do some static type checking.

We do this so real problems are found faster and the discussion about formatting is limited.
All of these can be installed by using ``pip``, but we recommend using them as a pre-commit hook. To activate that behaviour, do:

.. code-block:: bash

   $ pip install pre-commit
   $ pre-commit install


in your virtual environment.

Now each git commit will first run ``flake8``, then ``black`` and finally ``mypy`` over the files affected by the commit
(\ ``pre-commit`` will install these tools into its own structure on the first run).

This is also what happens automatically server-side when code is committed to a branch (via GitHub Actions), but having those tests locally as well will help you spot these issues faster.

If ``flake8``, ``black`` or ``mypy`` propose changes to any file, the commit is aborted (saying that it "failed"). 
The changes proposed by ``black`` are implemented automatically (you can review them with `git diff`). Some of them might even resolve the ``flake8`` warnings :)


Using Visual Studio, including spell checking
----------------------------------------------

Are you using Visual Studio Code? Then the code you just cloned also contains the editor configuration (part of) our team is using (see `.vscode`)!

We recommend installing the flake8 and spellright extensions.

For spellright, the FlexMeasures repository contains the project dictionary. Here are steps to link main dictionaries, which usually work on a Linux system:

.. code-block:: bash

   $ mkdir $HOME/.config/Code/Dictionaries
   $ ln -s /usr/share/hunspell/* ~/.config/Code/Dictionaries

Consult the extension's Readme for other systems.



A hint about using notebooks
---------------

If you edit notebooks, make sure results do not end up in git:

.. code-block:: bash

   $ conda install -c conda-forge nbstripout
   $ nbstripout --install


(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)



A hint for Unix developers
--------------------------------

I added this to my ~/.bashrc, so I only need to type ``fm`` to get started and have the ssh agent set up, as well as up-to-date code and dependencies in place.

.. code-block:: bash

   addssh(){
       eval `ssh-agent -s`
       ssh-add ~/.ssh/id_github
   }
   fm(){
       addssh
       cd ~/workspace/flexmeasures  
       git pull  # do not use if any production-like app runs from the git code                                                                                                                                                             
       workon flexmeasures-venv  # this depends on how you created your virtual environment
       make install-for-dev
   }


.. note:: All paths depend on your local environment, of course.

