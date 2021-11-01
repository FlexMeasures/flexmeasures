#!/bin/bash -e

# The purpose of this script is to deploy built and tested code to the staging server.
# You can use a git post-receive hook to update your app afterwards (see ci/Readme.md)

# Add a git remote (see developer docs on continuous integration for help)
git remote add staging $STAGING_REMOTE_REPO

# Push the branch being deployed to the git remote. Also push any annotated tags (with a -m message).
git push --follow-tags --set-upstream staging $BRANCH_NAME
