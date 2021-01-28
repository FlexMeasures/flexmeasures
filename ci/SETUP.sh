#!/bin/bash

##############################################
# This script sets up a new FlexMeasures instance
##############################################


# A secret key is used by Flask, for example, to encrypt the session
mkdir -p ./instance
head -c 24 /dev/urandom > ./instance/secret_key


# Install dependencies
apt-get update
apt-get -y install postgresql-client coinor-cbc
# set PGDB, PGUSER and PGPASSWORD as envs for this
psql -h localhost -p 5432 -c "create extension if not exists cube; create extension if not exists earthdistance;" -U $PGUSER $PGDB;
make install-deps


# Wait for the DB service to be up.

# Hack until this feature is ready: https://bitbucket.org/site/master/issues/15244/build-execution-should-wait-until-all
statusFile=/tmp/postgres-status
while [[ true ]]; do
  telnet 127.0.0.1 5432 &> ${statusFile}
  status=$(grep "Connection refused" ${statusFile} | wc -l)
  echo "Status: $status"

  if [[ "${status}" -eq 1 ]]; then
    echo "Postgres not running, waiting."
    sleep 1
  else
    rm ${statusFile}
    echo "Postgres running, ready to proceed."
    break;
  fi
done
