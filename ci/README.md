# Continuous integration

Here you can learn how to get FlexMeasures onto a server.

We talk about serving FlexMeasures in a WSGI setting and deploying on a server via git.

TODO: Dockerization


## WSGI configuration

Here is an example how to serve this application as WSGI app:


    # This file contains the WSGI configuration required to serve up your
    # web application.
    # It works by setting the variable 'application' to a WSGI handler of some description.

    import sys
    import os
    from dotenv import load_dotenv

    # add your project directory to the sys.path
    project_home = u'/path/to/your/code/flexmeasures'
    if project_home not in sys.path:
        sys.path = [project_home] + sys.path

    load_dotenv(os.path.join(project_home, '.env'))

    # create flask app - need to call it "application" for WSGI to work
    from flexmeasures.app import create as create_app
    application = create_app()


## Install the linear solver on the server

To compute schedules, FlexMeasures uses the [Cbc](https://github.com/coin-or/Cbc) mixed integer linear optimization solver.
It is used through [Pyomo](http://www.pyomo.org), so in principle supporting a [different solver](https://pyomo.readthedocs.io/en/stable/solving_pyomo_models.html#supported-solvers) would be possible.

Cbc needs to present on the server where FlexMeasures runs, under the `cbc` command.

You can install it on Debian like this:

    apt-get install coinor-cbc

If you can't use the package manager on your host, the solver has to be installed from source.
We provide [an example script](ci/install-cbc.sh) to do that, where you can also
pass a directory for the installation.

In case you want to install a later version, adapt the version in the script. 


## Automate deployment via Github actions

Github action workflows are in th e `.github/workflows` directory.
These workflows are triggered by commits being pushed to the repository, but it can also inspire your custom deployment script.
In `lint-and-test.yml`, we set up the app, run the tests and linters.
If testing succeeds and if the commit was on the `main` branch, `deploy.yml` deploys the code to a staging server (see below).


## Deployment on the server via Git

We support deployment of the FlexMeasures project on a staging server via Git checkout.

The deployment uses git's ability to push code to a remote upstream repository.
We trigger this deployment in `deploy.yml` (see above)
With the hooks functionality of Git, a post-receive script can then (re)start the FlexMeasures app.

### Remote origin

To see how a remote repo is added, see `DEPLOY.sh`. There, we add the remote and also push the current branch there.

To make this work, we need three things:

- Make sure the remote git repo exists (is cloned)
- Add the setting `STAGING_REMOTE_REPO` to the deployment environment (e.g. `deploy.yml` expects it in the repositiry secrets). An example value is `seita@ssh.our-server.com:/home/seita/flexmeasures-staging/flexmeasures.git`.
- Set up an SSH_DEPLOYMENT_KEY for deployment in the deployment environment (e.g. ), so that the server accepts the code. The public part should be in `~/.ssh/authorized_keys` on your server.


### Install Post-Receive Hook

Only pushing the code will not deploy the updated FlexMeasures. For this, we need to trigger a script.
Log on to the server (via SSH) and install the Git Post Receive Hook in the remote repo where we deployed the code (see above). This hook will be triggered when a push is received from the deployment environment.

The example script below can be a Post Receive Hook (save as `hooks/post-receive` in your remote origin repo and update paths).
It will force checkout the main branch, update dependencies, upgrade the database structure,
update the documentation and finally touch the wsgi.py file.
This last step is often a way to soft restart the running application, but here you need to adapt to your circumstances.


```#!/bin/bash
PATH_TO_GIT_WORK_TREE=/path/to/where/you/want/to/checkout/code/to
ACTIVATE_VENV="command-to-activate-your-venv"
PATH_TO_WSGI=/path/to/wsgi/script/for/the/app

echo "CHECKING OUT CODE TO GIT WORK TREE ($PATH_TO_GIT_WORK_TREE) ..."
GIT_WORK_TREE=$PATH_TO_GIT_WORK_TREE git checkout -f

cd $PATH_TO_GIT_WORK_TREE
PATH=$PATH_TO_VENV/bin:$PATH

echo "INSTALLING DEPENDENCIES ..."
make install-deps

echo "INSTALLING FlexMeasures ..."
make install-flexmeasures

echo "UPGRADING DATABASE STRUCTURE ..."
make upgrade-db

echo "UPDATING DOCUMENTATION ..."
make update-docs

echo "RESTARTING APPLICATION ..."
touch $PATH_TO_WSGI
```

