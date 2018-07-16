# Deployment

To deploy the Seita BVP project on PythonAnywhere follow these steps.

# Bitbucket Pipelines

The Bitbucket Pipeline is configured with the bitbucket-pipelines.yml file.
In this file we setup the project, run the tests and linters, and finish with
deploying the code to PythonAnywhere.

# Add PythonAnywhere Origin

The deployment uses the hooks functionality of Git. We add PythonAnywhere as a
remote origin and push to the PythonAnywhere git repo. The step below requires that
a deployment key be setup in the bvp Bitbucket repo. Once the code is built, the following
Git remote is added and the code is pushed. The below step pushes to the BVP staging repo.

```
git remote add pythonanywhere seita@ssh.pythonanywhere.com:/home/seita/bvp-staging

git push -u pythonanywhere $BITBUCKET_BRANCH
```

# Install Post-Receive Hook

On the PythonAnywhere server, ssh and install the Git Post Receive Hook
in the repo where you wish to deploy the final code. This will be triggered when a
push is received by the Bitbucket repo.

The script below can be a Post Receive Hook (save as `hooks/post-receive` in your remote origin repo and update paths).
It will force checkout the master branch,update dependencies, upgrade the database structure,
update the documentation and finally touch the wsgi.py file.
This last step is documented by PythonAnywhere as a way to soft restart the running application.


```#!/bin/bash
PATH_TO_GIT_WORK_TREE=/path/to/where/you/want/to/checout/code/to
ACTIVATE_VENV="command-to-activate-your-venv"
PATH_TO_WSGI=/path/to/wsgi/script/for/the/app

echo "CHECKING OUT CODE TO GIT WORK TREE ($PATH_TO_GIT_WORK_TREE) ..."
GIT_WORK_TREE=$PATH_TO_GIT_WORK_TREE git checkout -f

cd $PATH_TO_GIT_WORK_TREE
PATH=$PATH_TO_VENV/bin:$PATH                                                                                                                                                                                  

echo "INSTALLING DEPENDENCIES ..."
python setup.py develop

echo "UPGRADING DATABASE STRUCTURE ..."
flask db upgrade

echo "UPDATING DOCUMENTATION ..."
pip install sphinx sphinxcontrib.httpdomain
cd documentation; make html; cd ..

echo "RESTARTING APPLICATION ..."
touch $PATH_TO_WSGI
```
