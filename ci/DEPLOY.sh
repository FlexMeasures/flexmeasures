#!/bin/bash -e

: 'The purpose of this script is to deploy built and tested code
#to the staging server.
'

# Add PythonAnywhere as a git remote and push the code to that repo
git remote add pythonanywhere seita@ssh.pythonanywhere.com:/home/seita/bvp-staging

git push -u pythonanywhere $BITBUCKET_BRANCH