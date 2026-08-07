#!/bin/bash

# Call this script to create a fresh database, ready for development
# (also creates structure).
# It can also delete any existing one (will ask before).
#
# $ data/scripts/clean_database.sh <db-name> [<db-user>]
#
# The database user is optional. If you want to use an existing one,
# be aware that they might require privileges to access your new db.
#
# This works on Linux as well as on macOS.
# The Linux packages run the server under a dedicated "postgres" system account,
# which this script reaches through sudo.
# Homebrew and Postgres.app create no such account, and instead make the installing user a superuser,
# so on macOS the psql tooling is called directly, as the current user.

# save the current directory
MAIN_DIR=$(pwd)

# how we reach the server as a superuser depends on the platform
if [ "$(uname -s)" = "Darwin" ]; then
  # Homebrew and Postgres.app run the cluster as the user who installed it,
  # so no sudo and no explicit role are needed.
  SUPERUSER_PREFIX=()
  SUPERUSER_ROLE=()
else
  # The Linux packages hand ownership of the cluster to the "postgres" system account.
  SUPERUSER_PREFIX=(sudo -i -u postgres)
  SUPERUSER_ROLE=(-U postgres)
fi

# run psql as a superuser.
# Callers pass the database to connect to themselves, because psql would otherwise
# fall back to a database named after the current user, which macOS installs do have but Linux ones do not.
function psql_as_superuser() {
  "${SUPERUSER_PREFIX[@]}" psql "$@"
}

# run createdb/dropdb as a superuser
function createdb_as_superuser() {
  "${SUPERUSER_PREFIX[@]}" createdb "${SUPERUSER_ROLE[@]}" "$@"
}
function dropdb_as_superuser() {
  "${SUPERUSER_PREFIX[@]}" dropdb "${SUPERUSER_ROLE[@]}" "$@"
}

# quote a value as an SQL string literal, doubling any embedded single quote
function sql_literal() {
  local value=${1//\'/\'\'}
  printf "'%s'" "$value"
}

# quote a value as an SQL identifier, doubling any embedded double quote.
# Identifiers have to be quoted because an unquoted dash would be read as a minus sign,
# which is what made the documented "flexmeasures-db" fail here.
function sql_identifier() {
  local value=${1//\"/\"\"}
  printf '"%s"' "$value"
}

# fail early, and clearly, when the server cannot be reached at all
function check_server_is_reachable() {
  if psql_as_superuser -d postgres -tAc "SELECT 1" > /dev/null 2>&1; then
    return 0
  fi
  echo "Error: cannot connect to the PostgreSQL server as a superuser."
  if [ "$(uname -s)" = "Darwin" ]; then
    echo "Is the server running? With Homebrew, start it with 'brew services start postgresql'."
    echo "Note that Homebrew makes the installing user a superuser, so run this script as that user."
  else
    echo "Is the server running, and does the 'postgres' system account exist?"
  fi
  return 1
}

# function for checking database existence.
# We ask the catalog rather than grepping the output of psql -l,
# because grep -w treats a dash as a word boundary,
# so a name like "flexmeasures" would match an existing "flexmeasures-db".
function is_database() {
  psql_as_superuser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = $(sql_literal "$1")" | grep -q 1
}

# check if the user exists
function is_user() {
  if psql_as_superuser -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname = $(sql_literal "$1")" | grep -q 1; then
    echo "User $1 is already available."
    return 0 # success (user exists)
  else
    echo "User $1 is not created before."
    return 1 # failure (user does not exist)
  fi
}

# create a new user
function create_user() {
   echo "Creating database user ..."
   read -s -p "Enter password for new user: " password
   echo ""
   read -s -p "Confirm password for new user: " password_confirm
   echo ""

   if [ "$password" != "$password_confirm" ]; then
      echo "Error: Passwords do not match. Exiting..."
      return 1
   fi
   psql_as_superuser -d postgres -c "CREATE USER $(sql_identifier "$1") WITH PASSWORD $(sql_literal "$password")"
}

# function to give the required privileges to the newly created user
function grant_privileges(){
  echo "Connect $2 to $1 "
   psql_as_superuser -d postgres -c "GRANT CONNECT ON DATABASE $(sql_identifier "$1") TO $(sql_identifier "$2")"
   echo "Grant required privileges"
   psql_as_superuser -d "$1" -c "GRANT USAGE, SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO $(sql_identifier "$2")"
}

# function for creating a new database
function create_database() {
 echo "Creating a new database ..."
 if createdb_as_superuser "$1"; then
   echo "$1 database is created"
 else
   echo "$1 database cannot be created"
   return 1
 fi

 if [[ -n "$2" ]];
    then
      # check if the user already exists
      if is_user "$2"
        then
          # give the required permissions to the user
          grant_privileges "$1" "$2"
      else
        # if a user is created, then grant the required privileges
        if ! create_user "$2"
          then
            return 1
        else
          grant_privileges "$1" "$2"
        fi
      fi
 fi

 echo "Creating cube extension in $1 ..."
 psql_as_superuser -d "$1" -c "CREATE EXTENSION cube;"
 echo "Creating earthdistance extension in $1 ..."
 psql_as_superuser -d "$1" -c "CREATE EXTENSION earthdistance;"
 echo "Updating database structure ..."
 flexmeasures db upgrade
}

# function for deleting the old database
function delete_database() {
 echo "Dropping database ..."
 if dropdb_as_superuser "$1"; then
   echo "$1 database is dropped"
   return 0
 else
   echo "$1 database cannot be dropped"
   return 1
 fi
}

# Check if the database name is provided
if [ -z "$1" ]; then
  echo "Error: db-name is required. Please provide a value for db-name, e.g., uv run poe clean-db --db-name flexmeasures-db --db-user flexmeasures"
  exit 1
fi

# Check that we can talk to the server before doing anything else
if ! check_server_is_reachable; then
  exit 1
fi

# Check if the database exists
if is_database "$1"
then
  echo "$1 database exists"
  read -r -p "Make a backup first? [y/N] " response
  response=$(tr '[:upper:]' '[:lower:]' <<< $response) # make lowercase
  if [[ "$response" =~ ^(yes|y)$ ]]; then
    echo "Making db dump ..."
    flexmeasures db-ops dump
  fi

  read -r -p "This will drop your database and re-create a clean one. Continue?[y/N] " response
  response=$(tr '[:upper:]' '[:lower:]' <<< $response) # make lowercase
  if [[ "$response" =~ ^(yes|y)$ ]]; then
     if ! delete_database "$1"; then
       exit 1
     fi
     if ! create_database "$1" "$2"; then
       exit 1
     fi
  fi

# otherwise, create a fresh database
else
  echo "$1 database does not exist"
  if ! create_database "$1" "$2"; then
    exit 1
  fi
fi
