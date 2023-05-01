#!/bin/bash
# save the current directory
MAIN_DIR=$(pwd)

# function for checking database existence
function is_database() {
 cd /tmp
 sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -wq $1
 cd ${MAIN_DIR}
}

# function for creating a new database
function create_database() {
 echo "Creating a new database ..."
 sudo -i -u postgres createdb -U postgres $1
 echo "Creating cube extension in $1 ..."
 sudo -i -u postgres psql -c "\c $1" -c "CREATE EXTENSION cube;"
 echo "Creating earthdistance extension in $1 ..."
 sudo -i -u postgres psql -c "\c $1" -c "CREATE EXTENSION earthdistance;"
 echo "Updating database structure ..."
 flexmeasures db upgrade
}

# function for deleting the old database
function delete_database() {
 echo "Deleting database ..."
 sudo -i -u postgres dropdb -U postgres $1
}

# Check if the database name is provided
if [ -z "$1" ]; then
  echo "Error: db_name is required. Please provide a value for db_name, e.g., make clean_db db_name=flexmeasures-db"
  exit 1
fi

# Check if the database exists
if is_database $1
then
  echo "$1 exists"
  read -r -p "Make a backup first? [y/N] " response
  response=${response,,}    # make lowercase
  if [[ "$response" =~ ^(yes|y)$ ]]; then
    echo "Making db dump ..."
    flexmeasures db-ops dump
  fi

  read -r -p "This will drop your database and re-create a clean one. Continue?[y/N] " response
  response=${response,,} # make lowercase
  if [[ "$response" =~ ^(yes|y)$ ]]; then
     delete_database $1
     create_database $1
  fi

# otherwise, create a fresh database
else
  echo "$1 does not exist"
  create_database $1
fi