#!/bin/bash

######################################################################
# This script sets up a new Postgres instance in a CI environment
######################################################################


# Install dependencies
sudo apt-get update
sudo apt-get -y install postgresql-client

# Wait for the DB service to be up.

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

psql -h $PGHOST -p $PGPORT --file ci/load-psql-extensions.sql -U $PGUSER $PGDB;
