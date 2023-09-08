.. _deployment:

How to deploy FlexMeasures
===========================

Here you can learn how to get FlexMeasures onto a server.

.. note:: FlexMeasures can be deployed via Docker. Read more at :ref:`docker-image`. You need other components (e.g. postgres and redis) which are not handled here. See :ref:`docker-compose` for inspiration.

.. contents:: Table of contents
    :local:
    :depth: 1



WSGI configuration
------------------

On your own computer, ``flexmeasures run`` is a nice way to start FlexMeasures. On a production web server, you want it done the WSGI way. Here is an example how to serve FlexMeasures as WSGI app:

.. code-block:: python

   # This file contains the WSGI configuration required to serve up your
   # web application.
   # It works by setting the variable 'application' to a WSGI handler of some description.
   # The crucial part are the last two lines. We add some ideas for possible other logic.

   import os
   project_home = u'/path/to/your/code/flexmeasures'
   # use this if you want to load your own ``.env`` file.
   from dotenv import load_dotenv
   load_dotenv(os.path.join(project_home, '.env'))
   # use this if you run from source
   if project_home not in sys.path:
      sys.path = [project_home] + sys.path
   # adapt PATH to find our LP solver if it is installed from source
   os.environ["PATH"] = os.environ.get("PATH") + ":/home/seita/Cbc-2.9/bin"

   # create flask app - the name "application" has to be passed to the WSGI server
   from flexmeasures.app import create as create_app
   application = create_app()

The web server is told about the WSGI script, but also about the object which represents the application. For instance, if this script is called ``wsgi.py``, then the relevant argument to the gunicorn server is ``wsgi:application``.

Keep in mind that FlexMeasures is based on `Flask <https://flask.palletsprojects.com/>`_, so almost all knowledge on the web on how to deploy a Flask app also helps with deploying FlexMeasures. 


.. _installing-a-solver:

Install the linear solver on the server
---------------------------------------

To compute schedules, FlexMeasures uses the `HiGHS <https://highs.dev/>`_ mixed integer linear optimization solver (FlexMeasures solver by default) or `Cbc <https://github.com/coin-or/Cbc>`_.
Solvers are used through `Pyomo <http://www.pyomo.org>`_\ , so in principle supporting a `different solver <https://pyomo.readthedocs.io/en/stable/solving_pyomo_models.html#supported-solvers>`_ would be possible.

They need to be installed in addition to FlexMeasures. Here is advice on how to install the two solvers we test internally:


.. note:: We default to HiGHS, as it seems more powerful, but during unit tests we currently run Cbc, as it works for us on Python3.8


HiGHS can be installed using pip:

.. code-block:: bash

   $ pip install highspy


Cbc needs to be present on the server where FlexMeasures runs, under the ``cbc`` command.

You can install it on Debian like this:

.. code-block:: bash

   $ apt-get install coinor-cbc


If you can't use the package manager on your host, the solver has to be installed from source.
We provide an example script in ``ci/install-cbc-from-source.sh`` to do that, where you can also
pass a directory for the installation.

In case you want to install a later version, adapt the version in the script. 


