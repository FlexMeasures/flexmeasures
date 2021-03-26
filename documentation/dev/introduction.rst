
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


Auto-formatting
---------------

We use `Black <https://github.com/ambv/black>`_ to format our Python code and thus find real problems faster.
``Black`` can be installed in your editor, but we also use it as a pre-commit hook. To activate that behaviour, do:

.. code-block:: bash

   pip install pre-commit
   pre-commit install


in your virtual environment.

Now each git commit will first run ``black --diff`` over the files affected by the commit
(\ ``pre-commit`` will install ``black`` into its own structure on the first run).
If ``black`` proposes to edit any file, the commit is aborted (saying that it "failed"), 
and the proposed changes are printed for you to review.

With ``git ls-files -m | grep ".py" | xargs black`` you can apply the formatting, 
and make them part of your next commit (\ ``git ls-files`` cannot list added files,
so they need to be black-formatted separately).


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