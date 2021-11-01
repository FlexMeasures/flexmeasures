
Developing for FlexMeasures
===========================

This page instructs developers who work on FlexMeasures how to set up the development environment.
Furthermore, we discuss several guidelines and best practices.

.. contents:: Table of contents
    :local:
    :depth: 1

Getting started
------------------

Virtual environment
^^^^^^^^^^^^^^^^^^^^

Using a virtual environment is best practice for Python developers. We also strongly recommend using a dedicated one for your work on FlexMeasures, as our make target (see below) will use ``pip-sync`` to install dependencies, which could interfere with some libraries you already have installed.


* Make a virtual environment: ``python3.8 -m venv flexmeasures-venv`` or use a different tool like ``mkvirtualenv`` or virtualenvwrapper. You can also use
  an `Anaconda distribution <https://conda.io/docs/user-guide/tasks/manage-environments.html>`_ as base with ``conda create -n flexmeasures-venv python=3.8``.
* Activate it, e.g.: ``source flexmeasures-venv/bin/activate``

Dependencies
^^^^^^^^^^^^^^^^^^^^

Install all dependencies including the ones needed for development:

.. code-block:: bash

   make install-for-dev


Configuration
^^^^^^^^^^^^^^^^^^^^

Follow the configuration Quickstart advice in :ref:`getting_started` and :ref:`configuration`.


Loading data
^^^^^^^^^^^^^^^^^^^^

If you have a SQL Dump file, you can load that:

.. code-block:: bash

   psql -U {user_name} -h {host_name} -d {database_name} -f {file_path}


Run locally
^^^^^^^^^^^^^^^^^^^^

Now, to start the web application, you can run:

.. code-block:: bash

   flexmeasures run


Or:

.. code-block:: bash

   python run-local.py


And access the server at http://localhost:5000


Logfile
--------

FlexMeasures logs to a file called ``flexmeasures.log``. You'll find this in the application's context folder, e.g. where you called ``flexmeasures run``.

A rolling log file handler is used, so if ``flexmeasures.log`` gets to a few megabytes in size, it is copied to `flexmeasures.log.1` and the original file starts over empty again. 

The default logging level is ``WARNING``. To see more, you can update this with the config setting ``LOGGING_LEVEL``, e.g. to ``INFO`` or ``DEBUG``


Tests
-----

You can run automated tests with:

.. code-block:: bash

   make test


which behind the curtains installs dependencies and calls pytest.

A coverage report can be created like this:

.. code-block:: bash

   pytest --cov=flexmeasures --cov-config .coveragerc


You can add --cov-report=html after which a htmlcov/index.html is generated.

It's also possible to use:

.. code-block:: bash

   python setup.py test



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

   pip install pre-commit
   pre-commit install


in your virtual environment.

Now each git commit will first run ``flake8``, then ``black`` and finally ``mypy`` over the files affected by the commit
(\ ``pre-commit`` will install these tools into its own structure on the first run).

This is also what happens automatically server-side when code is committed to a branch (via Github Actions), but having those tests locally as well will help you spot these issues faster.

If ``flake8``, ``black`` or ``mypy`` propose changes to any file, the commit is aborted (saying that it "failed"). 
The changes proposed by ``black`` are implemented automatically (you can review them with `git diff`). Some of them might even resolve the ``flake8`` warnings :)



A hint about using notebooks
---------------

If you edit notebooks, make sure results do not end up in git:

.. code-block:: bash

   conda install -c conda-forge nbstripout
   nbstripout --install


(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)



A hint for Unix developers
--------------------------------

I added this to my ~/.bashrc, so I only need to type ``fm`` to get started and have the ssh agent set up, as well as up-to-date code and dependencies in place.

.. code-block:: bash

   addssh(){
       eval `ssh-agent -s`
       ssh-add ~/.ssh/id_bitbucket
   }
   fm(){
       addssh
       cd ~/workspace/flexmeasures  
       git pull  # do not use if any production-like app runs from the git code                                                                                                                                                             
       workon flexmeasures-venv  # this depends on how you created your virtual environment
       make install-for-dev
   }


.. note:: All paths depend on your local environment, of course.