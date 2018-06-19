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
push is received by the Bitbucket repo. The script below will force checkout the master
branch and finally will touch the wsgi.py file. This is documented by PythonAnywhere as
a way to soft restart the running application.

```
#!/bin/bash
GIT_WORK_TREE=/path/to/bvp/work/tree git checkout -f 
touch /var/www/staging_a1-bvp_com_wsgi.py
```
