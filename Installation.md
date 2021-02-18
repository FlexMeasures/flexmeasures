# Building & Running FlexMeasures


## Dependencies

Install dependencies and the `flexmeasures` platform itself:

      make install

## Configure environment

* Set an env variable to indicate in which environment you are operating (one out of development|testing|staging|production), e.g.:

    `echo "FLASK_ENV=development" >> .env`

    `export FLASK_ENV=production`
* If you need to customise settings, create `flexmeasures/<development|testing|staging|production>_config.py` and add required settings.
  If you're unsure what you need, just continue for now and the app will tell you what it misses.

## Make a secret key for sessions

    mkdir -p /path/to/flexmeasures/instance
    head -c 24 /dev/urandom > /path/to/flexmeasures/instance/secret_key

## Preparing the time series database

* Make sure you have a Postgres (Version 9+) database. See `data/Readme.md` for instructions on this.
* Tell `flexmeasures` about it. Either you are using the default for the environment you're in (see `flexmeasures/utils/config_defaults`),
   or you can configure your own connection string: In `flexmeasures/<development|testing|staging|production>_conf.py`,
  set the variable `SQLALCHEMY_DATABASE_URI = 'postgresql://<user>:<password>@<host-address>[:<port>]/<db>'`
* Run `flask db upgrade` to create the Postgres DB structure.

## Preparing the job queue database

To let FlexMeasures queue forecasting and scheduling jobs, install a Redis server and configure access to it within FlexMeasures' config file (see above). You can find the default settings in `flexmeasures/utils/config_defaults.py`.

TODO: more detail

## Install an LP solver

For planning balancing actions, the flexmeasures platform uses a linear program solver. Currently that is the Cbc solver. See the `FLEXMEASURES_LP_SOLVER` config setting if you want to change to a different solver.

Installing Cbc can be done on Unix via:

    apt-get install coinor-cbc

(also available in different popular package managers).

We provide a script for installing from source (without requiring `sudo` rights) in [the CI Readme](ci/Readme.md).

More information (e.g. for installing on Windows) on [the website](https://projects.coin-or.org/Cbc).


## Run

Now, to start the web application, you can run:

    python flexmeasures/run-local.py

But in a production context, you shouldn't run a script - hand the `app` object to a WSGI process, as your platform of choice describes.

Often, that requires a WSGI script. We provide an example WSGI script in [the CI Readme](ci/Readme.md).


## Loading data

If you have a SQL Dump file, you can load that:

    psql -U {user_name} -h {host_name} -d {database_name} -f {file_path}

Else, you can populate some standard data, most of which comes from files:

* Finally, run `flask db_populate --structure --data --small` to load this data into the database.
  The `--small` parameter will only load four assets and four days, so use this first to try things out. TODO: check which command is possible at the moment. Also add a TODO saying where we want to go with this (support for loading data).


