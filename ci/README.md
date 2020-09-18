# WSGI configuration

Here is an example how to serve this application as WSGI app:


    # This file contains the WSGI configuration required to serve up your
    # web application at http://<your-username>.pythonanywhere.com/
    # It works by setting the variable 'application' to a WSGI handler of some
    # description.
    #
    # The below has been auto-generated for your Flask project

    import sys
    import os
    from dotenv import load_dotenv

    # add your project directory to the sys.path
    project_home = u'/path/to/your/code/bvp'
    if project_home not in sys.path:
        sys.path = [project_home] + sys.path

    load_dotenv(os.path.join(project_home, '.env'))

    # create flask app - need to call it "application" for WSGI to work
    from bvp.app import create as create_app
    application = create_app()

# Deployment

To deploy the Seita BVP project on PythonAnywhere follow these steps.

## Bitbucket Pipelines

The Bitbucket Pipeline is configured with the bitbucket-pipelines.yml file.
In this file we setup the project, run the tests and linters, and finish with deploying the code to PythonAnywhere.

## Add PythonAnywhere Origin

The deployment uses the hooks functionality of Git. We add PythonAnywhere as a
remote origin and push to the PythonAnywhere git repo. The step below requires that
a deployment key be setup in the bvp Bitbucket repo. Once the code is built, the following
Git remote is added and the code is pushed. The below step pushes to the BVP staging repo.

```
git remote add pythonanywhere seita@ssh.pythonanywhere.com:/home/seita/bvp-staging

git push --follow-tags -u pythonanywhere $BITBUCKET_BRANCH
```

## Install Post-Receive Hook

On the PythonAnywhere server, ssh and install the Git Post Receive Hook
in the repo where you wish to deploy the final code. This will be triggered when a push is received by the Bitbucket repo.

The script below can be a Post Receive Hook (save as `hooks/post-receive` in your remote origin repo and update paths).
It will force checkout the master branch, update dependencies, upgrade the database structure,
update the documentation and finally touch the wsgi.py file.
This last step is documented by PythonAnywhere as a way to soft restart the running application.


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

echo "INSTALLING BVP ..."
make install-bvp

echo "UPGRADING DATABASE STRUCTURE ..."
make upgrade-db

echo "UPDATING DOCUMENTATION ..."
make update-docs

echo "RESTARTING APPLICATION ..."
touch $PATH_TO_WSGI
```


## Install the linear solver

The Cbc solver has to be installed from source.
We provide [an example script to that](ci/install-cbc.sh). You might want to install a later version, then adapt the version in the script. 