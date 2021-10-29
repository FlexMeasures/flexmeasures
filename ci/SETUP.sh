#!/bin/bash

######################################################################
# This script sets up a new FlexMeasures instance in a CI environment
######################################################################


# Install dependencies
apt-get update
sudo apt-get -y install postgresql-client coinor-cbc
make install-deps


# Wait for the DB service to be up.

# Hack until this feature is ready: https://bitbucket.org/site/master/issues/15244/build-execution-should-wait-until-all
statusFile=/tmp/postgres-status
while [[ true ]]; do
  telnet $PGHOST $PGPORT &> ${statusFile}
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

psql -h $PGHOST -p $PGPORT -c "create extension if not exists cube; create extension if not exists earthdistance;" -U $PGUSER $PGDB;
