.. _deployment:

How to deploy FlexMeasures
===========================

Here you can learn how to get FlexMeasures onto a server.

.. note:: FlexMeasures can be deployed via Docker, where the solver is already installed and there are cloud infrastructures like Kubernetes you'd use. Read more at :ref:`docker-image`. You need other components (e.g. postgres and redis) which are not handled here. See :ref:`docker-compose` for inspiration.



WSGI configuration
------------------

On your own computer, ``flexmeasures run`` is a nice way to start FlexMeasures. On a production web server, you want it done the :abbr:`WSGI (Web Server Gateway Interface)` way. 

Here, you'd want to hand FlexMeasures' ``app`` object to a WSGI process, as your platform of choice describes.
Often, that requires a WSGI script. Below is a minimal example. 


.. code-block:: python
   
   # use this if you run from source, not needed if you pip-installed FlexMeasures
   project_home = u'/path/to/your/code/flexmeasures'
   if project_home not in sys.path:
      sys.path = [project_home] + sys.path
   
   # create flask app - the name "application" has to be passed to the WSGI server
   from flexmeasures.app import create as create_app
   application = create_app()

The web server is told about the WSGI script, but also about the object that represents the application.
For instance, if this script is called wsgi.py, then the relevant argument to the gunicorn server is `wsgi:application`.

A more nuanced one from our practice is this:

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


Keep in mind that FlexMeasures is based on `Flask <https://flask.palletsprojects.com/>`_, so almost all knowledge on the web on how to deploy a Flask app also helps with deploying FlexMeasures. 


.. _installing-a-solver:

Install the linear solver on the server
---------------------------------------

To compute schedules, FlexMeasures uses the `HiGHS <https://highs.dev/>`_ mixed integer linear optimization solver (FlexMeasures solver by default) or `Cbc <https://github.com/coin-or/Cbc>`_.
Solvers are used through `Pyomo <http://www.pyomo.org>`_\ , so in principle supporting a `different solver <https://pyomo.readthedocs.io/en/stable/solving_pyomo_models.html#supported-solvers>`_ would be possible.

You tell FlexMeasures with the config setting :ref:`solver-config` which solver to use.

However, the solver also needs to be installed - in addition to FlexMeasures (the Docker image already has it). Here is advice on how to install the two solvers we test internally:


.. note:: We default to HiGHS, as it seems more powerful


HiGHS can be installed using pip:

.. code-block:: bash

   $ pip install highspy

More information on `the HiGHS website <https://highs.dev/>`_.

Cbc needs to be present on the server where FlexMeasures runs, under the ``cbc`` command.

You can install it on Debian like this:

.. code-block:: bash

   $ apt-get install coinor-cbc

(also available in different popular package managers).

More information is on `the CBC website <https://projects.coin-or.org/Cbc>`_.

If you can't use the package manager on your host, the solver has to be installed from source.
We provide an example script in ``ci/install-cbc-from-source.sh`` to do that, where you can also
pass a directory for the installation.

In case you want to install a later version, adapt the version in the script. 
