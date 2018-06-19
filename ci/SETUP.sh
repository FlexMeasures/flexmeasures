#!/bin/bash

# Secret key is used by Flask for encrypting the session keys for example
mkdir -p ./instance
head -c 24 /dev/urandom > ./instance/secret_key

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
