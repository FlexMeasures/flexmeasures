.. _deployment:

How to deploy FlexMeasures
===========================

Here you can learn how to get FlexMeasures onto a server.

.. contents:: Table of contents
    :local:
    :depth: 1

.. todo:: It would be great to enable Dockerization of FlexMeasures, let us know if this matters to you.


WSGI configuration
------------------

On your own computer, ``flexmeasures run`` is a nice way to start FlexMeasures. On a production web server, you want it done the WSGI way. Here is an example how to serve FlexMeasures as WSGI app:

.. code-block:: python

   # This file contains the WSGI configuration required to serve up your
   # web application.
   # It works by setting the variable 'application' to a WSGI handler of some description.

   import os
   from dotenv import load_dotenv

   project_home = u'/path/to/your/code/flexmeasures'
   load_dotenv(os.path.join(project_home, '.env'))

   # create flask app - need to call it "application" for WSGI to work
   from flexmeasures.app import create as create_app
   application = create_app()

Keep in mind that FlexMeasures is based on `Flask <https://flask.palletsprojects.com/>`_, so almost all knowledge on the web on how to deploy a Flask app also helps with deploying FlexMeasures. 


Install the linear solver on the server
---------------------------------------

To compute schedules, FlexMeasures uses the `Cbc <https://github.com/coin-or/Cbc>`_ mixed integer linear optimization solver.
It is used through `Pyomo <http://www.pyomo.org>`_\ , so in principle supporting a `different solver <https://pyomo.readthedocs.io/en/stable/solving_pyomo_models.html#supported-solvers>`_ would be possible.

Cbc needs to be present on the server where FlexMeasures runs, under the ``cbc`` command.

You can install it on Debian like this:

.. code-block:: console

   apt-get install coinor-cbc


If you can't use the package manager on your host, the solver has to be installed from source.
We provide `an example script <ci/install-cbc.sh>`_ to do that, where you can also
pass a directory for the installation.

In case you want to install a later version, adapt the version in the script. 

