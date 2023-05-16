#!/bin/bash
# save the current directory
MAIN_DIR=$(pwd)

# function for checking database existence
function is_database() {
  sudo -i -u postgres psql -lqt | cut -d \| -f 1 | grep -wq $1
}

# check if the user exists
function is_user() {
  if sudo -i -u postgres psql -tAc "SELECT 1 FROM  pg_roles WHERE rolname='$1'" | grep -q 1; then
    echo "$1 is already available."
    return 0 # success (user exists)
  else
    echo "$1 is not created before."
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
      exit 1
   fi
   sudo -i -u postgres psql -c "CREATE USER $1 WITH PASSWORD '$password'"
}

# function to give the required privileges to the newly created user
function grant_privileges(){
  echo "Connect $2 to $1 "
   sudo -i -u postgres psql -c "GRANT CONNECT ON DATABASE $1 TO $2"
   echo "Grant required privileges"
   sudo -i -u postgres psql -c "GRANT USAGE, SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO $2"
}

# function for creating a new database
function create_database() {
 echo "Creating a new database ..."
 sudo -i -u postgres createdb -U postgres $1

 if [[ -n "$2" ]];
    then
      # check if the user exists
      if is_user $2
        then
          # give the required permissions to the user
          grant_privileges $1 $2
      else
        # if user doesn't exist, first create it and then give the permissions.
        if create_user $2
          then
            grant_privileges $1 $2
        fi
      fi
 fi

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
  echo "Error: db_name is required. Please provide a value for db_name, e.g., make clean-db db_name=flexmeasures-db [db_user=flexmeasures]"
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
     create_database $1 $2
  fi

# otherwise, create a fresh database
else
  echo "$1 does not exist"
  create_database $1 $2
fi
