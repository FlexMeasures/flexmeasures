Automate deployment via Github actions and Git
===============================================

Here is an idea which we are not actively using anymore, but might be useful for you if you clone FlexMeasures or derive a new project from it via a plugin.
Or we pick it up again in the future - who knows.

The idea is to update a live server running FlexMeasures each time code is merged to the main branch.
That would usually be a staging server, to test if everything responds okay. 

Below, we show how to add a GitHub Action workflow (see the ``.github/workflows`` directory) to push to a remote upstream repository.

The GitHub Actions workflows are triggered by commits being pushed to the repository, but it can also inspire your custom deployment script.

Why don't we use it for the FlexMeasures repo anymore? It requires a live server, which we cannot provide at the moment for the project, and we also added a Build step which tests everything in a Docker image.
At Seita, we use FlexMeasures in combination with various plugins, and we built a staging server which uses our whole stack.


Let's get started!

In the following, we'll refer to GitHub Actions as our "CI environment" and our staging server as the "deployment server". 

*
  We add a GitHub Action workflow to ``deploy.yml``, which runs if the commit was on the ``main `` branch, waits for our CI test workflow, and then pushes the code to a remote repo on the deployment server.

*
  We explain how to make this git push to that remote repo happen.

* 
  And of course, the CI environment needs to properly authenticate at the deployment server. 

* 
  With the hooks functionality of Git, a post-receive script can then (re-)start the FlexMeasures app on the deployment server.


Let's review these four steps in detail:


Adding the GitHub Action workflow
------------------------------------------------

Add the following as ``.github/workflows/deploy.yml``:

.. code-block:: bash

    name: deploy-to-staging

    on: 
    push:
        branches:
        - main

    jobs:
    deploy:
        name: "Deploy (main to staging)"
        runs-on: ubuntu-latest
        steps:
        - name: Wait for tests to pass
            uses: lewagon/wait-on-check-action@v0.2
            with:
            ref: ${{ github.ref }}
            # check-name: "Test (on Python3.9)" # name of the job we wait for (omit to wait for all checks)
            running-workflow-name: "Deploy (main to staging)"  # name of the check that will wait for other checks
            repo-token: ${{ secrets.GITHUB_TOKEN }}
            wait-interval: 20 # seconds
        - uses: actions/checkout@v3
            with:
            fetch-depth: '0'
            ref: 'main'
        - name: Install SSH key
            uses: shimataro/ssh-key-action@v2
            with:
            key: ${{ secrets.SSH_DEPLOYMENT_KEY }}  # private ssh key
            known_hosts: ${{ secrets.KNOWN_DEPLOYMENT_HOSTS }}  # make via ssh-keyscan -t rsa <your host>
        - run: DEPLOY.sh
        env:
        BRANCH_NAME: main
        STAGING_REMOTE_REPO: ${{ secrets.STAGING_REMOTE_REPO }}

We'll explain what ``DEPLOY.sh`` is and how to configure the env variables below.


Add a script to 

Using git to deploy code (remote upstream)
------------------------------------------------

Deployment of the FlexMeasures project on a staging server happens via Git checkout.

The deployment uses git's ability to push code to a remote upstream repository. This repository needs to be installed on your staging server.

Add this script and call it ``DEPLOY.sh``:

.. code-block:: bash

    #!/bin/bash -e

    # The purpose of this script is to deploy built and tested code to the staging server.
    # You can use a git post-receive hook to update your app afterwards (see ci/Readme.md)

    # Add a git remote (see developer docs on continuous integration for help)
    git remote add staging $STAGING_REMOTE_REPO

    # Push the branch being deployed to the git remote. Also push any annotated tags (with a -m message).
    git push --follow-tags --set-upstream staging $BRANCH_NAME

To recap: We trigger this deployment in ``deploy.yml`` and it's being done in ``DEPLOY.sh``. There, we add the remote and then push the current branch to it.

We thus need to tell the deployment environment two things:


* Add the setting ``STAGING_REMOTE_REPO`` as an environment variable on the CI environment (e.g. ``deploy.yml`` expects it in the Github repository secrets). An example value is ``seita@ssh.our-server.com:/home/seita/flexmeasures-staging/flexmeasures.git``. So in this case, ``ssh.our-server.com`` is the deployment server, which we'll also use below. `seita` needs to become your ssh username on that server and the rest is the path to where you want to check out the repo.
* Make sure the env variable ``BRANCH_NAME`` is set, e.g. to "main", so that the CI environment knows what exact code to push to your deployment server.


Authenticate at the deployment server (with an ssh key)
------------------------------------------------

For CI environment and deployment server to interact securely, we of course need to put in place some authentication measures.  

First, they need to know each other. Let the deployment server know it's okay to talk to the CI environment, by adding an entry to ``~/.ssh/known_hosts``. Similarly, you might need to let the CI environment know it's okay to talk to the deployment server (e.g. in our Github Actions config, ``deploy.yml`` expects this entry in the Github repository secrets as ``KNOWN_DEPLOYMENT_HOSTS``\ ).

You can create these entries with ``ssh-keyscan -t rsa <your host>``, where host might be `github.com` or `ssh.our-server.com` (see above).

Second, the CI environment needs to authenticate at the deployment server using an SSH key pair. 

Use ``ssh-keygen`` to create one, using no password.

* Add the private part of this ssh key pair to the CI environment, so that the deployment server can accept the pushed code. (e.g. as ``~/.ssh/id_rsa``\ ). In ``deploy.yml``\ , we expect it as the secret ``SSH_DEPLOYMENT_KEY``\ , which adds the key for us.
* Finally, the public part of the key pair should be in ``~/.ssh/authorized_keys`` on your deployment server.


(Re-)start FlexMeasures on the deployment server (install Post-Receive Hook)
------------------------------------------------

Only pushing the code will not actually deploy the updated FlexMeasures into a usable web app on the deployment server. For this, we need to trigger a script.

Log on to the deployment server (via SSH) and install a script to (re-)start FlexMeasures as a Git Post Receive Hook in the remote repo where we deployed the code (see above). This hook will be triggered whenever a push is received from the deployment environment.

The example script below can be a Post Receive Hook (save as ``hooks/post-receive`` in your remote origin repo and update paths).
It will force a checkout of the main branch into our working directory, update dependencies, upgrade the database structure and finally touch the wsgi.py file.

.. note:: Note that we are not installing FlexMeasures itself (that would require ``make install-flexmeasures``, which essentially is ``python setup.py develop``), as that is not needed for our base requirement here: to run this checked-out code with a web server that uses a WSGI file to define the app. Running CLI commands will not work without installation. Also, installing FlexMeasures requires a version, which is gotten from the git status (via setuptool_scm). We are working on a checked-out copy of the git code here without git meta information, so installing would fail anyways.

The last step, touching a wsgi.py file, is often used as a way to soft-restart the running application ― here you need to adapt to your circumstances.

.. code-block:: bash

    #!/bin/bash

   PATH_TO_GIT_WORK_TREE=/path/to/where/you/want/to/checkout/code/to
   ACTIVATE_VENV="command-to-activate-your-venv"
   PATH_TO_WSGI=/path/to/wsgi/script/for/the/app

   echo "CHECKING OUT CODE TO GIT WORK TREE ($PATH_TO_GIT_WORK_TREE) ..."
   GIT_WORK_TREE=$PATH_TO_GIT_WORK_TREE git checkout -f

   cd $PATH_TO_GIT_WORK_TREE
   PATH=$PATH_TO_VENV/bin:$PATH

   echo "INSTALLING DEPENDENCIES ..."
   make install-deps

   echo "UPGRADING DATABASE STRUCTURE ..."
   make upgrade-db

   echo "RESTARTING APPLICATION ..."
   touch $PATH_TO_WSGI


A WSGI file can do various things, as well, but the simplest form is shown below.

.. code-block:: python

  from flexmeasures.app import create as create_app

  application = create_app()


The web server is told about the WSGI script, but also about the object which represents the application. For instance, if this script is called ``wsgi.py``, then the relevant argument to the gunicorn server is ``wsgi:application``.