#!/bin/bash

# FlexMeasures wrapper script with database connection fix
# This script sets the correct database URL via environment variable to bypass config file parsing issues

export SQLALCHEMY_DATABASE_URI="postgresql://flexmeasures-user:FMPass@localhost:5432/flexmeasures-db"

# Run flexmeasures with any arguments passed to this script
flexmeasures "$@"
