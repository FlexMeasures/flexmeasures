#!/bin/bash -e

# The purpose of this script is to deploy built and tested code
# to the staging server.

# Add PythonAnywhere as a git remote and push the code to that repo
git remote add pythonanywhere seita@ssh.pythonanywhere.com:/home/seita/bvp-staging/bvp.git

# Push the branch being deployed to the PythonAnywhere remote. Also push any annotated tags (with a -m message).
git push --follow-tags -u pythonanywhere $BITBUCKET_BRANCH
