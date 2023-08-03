#!/bin/bash

#################################################################################
# This script installs the Cbc solver from source
# (for cases where you can't install the coinor-cbc package via package managers)
# Note: We use 2.9 here, but 2.10 has also been working well in our CI pipeline.
#################################################################################

# Install to this dir
SOFTWARE_DIR=/home/seita/software
if [ "$1" != "" ]; then
  SOFTWARE_DIR=$1
fi
echo "Attempting to install Cbc-2.9 to $SOFTWARE_DIR ..."

mkdir -p $SOFTWARE_DIR
cd $SOFTWARE_DIR

# Getting Cbc and its build tools
git clone --branch=stable/2.9 https://github.com/coin-or/Cbc Cbc-2.9
cd Cbc-2.9
git clone --branch=stable/0.8 https://github.com/coin-or-tools/BuildTools/
BuildTools/get.dependencies.sh fetch

# Configuring, installing
./configure
make
make install

# adding new binaries to PATH
# NOTE: This line might need to be added to your ~/.bashrc or the like
export PATH=$PATH:$SOFTWARE_DIR/Cbc-2.9/bin

echo "Done. The command 'cbc' should now work on this machine."