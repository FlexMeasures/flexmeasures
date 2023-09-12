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
  exit 1
fi

SOURCE_DIR=$(pwd)/../

TEMP_DIR=$(mktemp -d)

# Copy the current directory to the temp directory
cp -r ../ $TEMP_DIR

cd $TEMP_DIR

PYTHON_VERSIONS=(3.8 3.9 3.10 3.11)

for PYTHON_VERSION in "${PYTHON_VERSIONS[@]}"
do
    # Remove container if it exists
    docker rm --force flexmeasures-update-packages-$PYTHON_VERSION || true
    # Build the docker image
    docker build --build-arg=PYTHON_VERSION=$PYTHON_VERSION -t flexmeasures-update-packages:$PYTHON_VERSION . -f ci/Dockerfile.update
    # Build flexmeasures
    docker run --name flexmeasures-update-packages-$PYTHON_VERSION -it flexmeasures-update-packages:$PYTHON_VERSION make upgrade-deps docker=yes
    # Copy the requirements to the source directory
    docker cp flexmeasures-update-packages-$PYTHON_VERSION:/app/requirements/$PYTHON_VERSION $SOURCE_DIR/requirements/
    # Remove the container
    docker rm flexmeasures-update-packages-$PYTHON_VERSION
    # Remove the image
    docker rmi flexmeasures-update-packages:$PYTHON_VERSION
done

# Clean up docker builder cache
# docker builder prune --all -f

# Remove the temp directory
rm -rf $TEMP_DIR