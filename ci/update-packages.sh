#!/bin/bash

######################################################################
# This script sets up the docker environment for updating packages
######################################################################

set -e
set -x

# Check if docker is installed
if ! [ -x "$(command -v docker)" ]; then
  echo "Docker is not installed. Please install docker and try again."
  exit 1
fi

# Check if we can run docker without sudo
if ! docker ps > /dev/null 2>&1; then
  echo "Docker is not running without sudo. Please add your user to the docker group and try again."
  echo "You may use the following command to do so:"
  echo "sudo usermod -aG docker $USER"
  echo "You will need to log out and log back in for this to take effect."
  exit 1
fi

SOURCE_DIR=$(pwd)/../

TEMP_DIR=$(mktemp -d)

# Copy the build files to the temp directory
cp -r ../ci $TEMP_DIR/ci
cp -r ../requirements $TEMP_DIR/requirements
cp -r ../Makefile $TEMP_DIR

cd $TEMP_DIR

PYTHON_VERSIONS=(3.8 3.9 3.10 3.11)

for PYTHON_VERSION in "${PYTHON_VERSIONS[@]}"
do
    # Check if container exists and remove it
    docker container inspect flexmeasures-update-packages-$PYTHON_VERSION > /dev/null 2>&1 && docker rm --force flexmeasures-update-packages-$PYTHON_VERSION
    # Build the docker image
    docker build --build-arg=PYTHON_VERSION=$PYTHON_VERSION -t flexmeasures-update-packages:$PYTHON_VERSION . -f ci/Dockerfile.update
    # Build flexmeasures
    # We are disabling running tests here, because we only want to update the packages. Running tests would require us to setup a postgres database,
    # which is not necessary for updating packages.
    docker run --name flexmeasures-update-packages-$PYTHON_VERSION -it flexmeasures-update-packages:$PYTHON_VERSION make upgrade-deps skip-test=yes
    # Copy the requirements to the source directory
    docker cp flexmeasures-update-packages-$PYTHON_VERSION:/app/requirements/$PYTHON_VERSION $SOURCE_DIR/requirements/
    # Remove the container
    docker rm flexmeasures-update-packages-$PYTHON_VERSION
    # Remove the image
    docker rmi flexmeasures-update-packages:$PYTHON_VERSION
done

# Clean up docker builder cache
echo "You can clean up the docker builder cache with the following command:"
echo "docker builder prune --all -f"

# Remove the temp directory
rm -rf $TEMP_DIR