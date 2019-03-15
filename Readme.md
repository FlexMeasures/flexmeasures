# Balancing Valorisation Platform (BVP)

This is Seita's implementation of the BVP pilot for A1.

The *Balancing Valorisation Platform (BVP)* is a tool for scheduling balancing actions on behalf of the connected asset owners.
Its purpose is to offer these balancing actions as one aggregated service to energy markets, realising the highest possible value for its users.


## Build & Run


### Make a secret key for sessions:

    mkdir -p /path/to/bvp/instance
    head -c 24 /dev/urandom > /path/to/bvp/instance/secret_key


### Dependencies:

* Make a virtual environment: `python3.6 -m venv bvp-venv` or use a different tool like `mkvirtualenv`. You can also use
  an [Anaconda distribution](https://conda.io/docs/user-guide/tasks/manage-environments.html) as base with `conda create -n bvp-venv python=3.6`.
* Activate it, e.g.: `source bvp-venv/bin/activate`
* Install the `bvp` platform and dependencies:

      python setup.py [develop|install]



### Configure environment

* Set an env variable to indicate in which environment you are operating (one out of development|testing|staging|production), e.g.:

    `echo "FLASK_ENV=development" >> .env`
    
    `export FLASK_ENV=production`
* If you need to customise settings, create `bvp/<development|testing|staging|production>_config.py` and add required settings.
  If you're unsure what you need, just continue for now and the app will tell you what it misses.


### Prepare & load data:

#### Preparing a database

* Make sure you have a Postgres (Version 9+) database.
* Tell `bvp` about it. Either you are using the default for the environment you're in (see `bvp/utils/config_defaults`),
   or you can configure your own connection string: In `bvp/<development|testing|staging|production>_conf.py`,
  set the variable `SQLALCHEMY_DATABASE_URI = 'postgresql://<user>:<password>@<host-address>[:<port>]/<db>'`
* Run `flask db upgrade` to create the Postgres DB structure.


#### Loading data

If you have a SQL Dump file, you can load that:

    psql -U {user_name} -h {host_name} -d {database_name} -f {file_path}
    
Else, you can populate some standard data, most of which comes from files:

* For meta data, ask someone for `raw_data/assets.json`
* For time series data: 
  - Either ask someone for pickled dataframes, to be put in `data/pickles`
  - Or get the pickles from the source:
     - Ask someone for `raw_data/20171120_A1-VPP_DesignDataSetR01.xls` (Excel sheet provided by A1 to Seita),
       `raw_data/German day-ahead prices 20140101-20160630.csv` (provided by Seita)
       and `raw_data/German charging stations 20150101-20150620.csv` (provided by Seita).
       You probably also need to create the folder data/pickles.
    - Install `python3.6-dev` by apt-get or so, as well as `xlrd` and `fbprophet` by pip.
    - Run `python bvp/data/scripts/init_timeseries_data.py`
* Finally, run `flask db_populate --structure --data --small` to load this data into the database.
  The `--small` parameter will only load four assets and four days, so use this first to try things out.


### Install an LP solver

For planning balancing actions, the BVP platform uses a linear program solver. Currently that is the Cbc solver. See the `BVP_LP_SOLVER` config setting if you want to change to a different solver.

Installing Cbc can be done on Unix via ``apt-get install coinor-cbc`` (also available in different popular package managers).

Installing without `sudo` rights on Unix is also possible. This should give an indication:

```bash
#!/bin/bash

# Install to this dir
SOFTWARE_DIR=/home/seita/software

mkdir -p $SOFTWARE_DIR
cd $SOFTWARE_DIR

# Getting Cbc abd its build tools
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
```

More information (e.g. for installing on Windows) on [the website](https://projects.coin-or.org/Cbc).


### Done.

Now, to start the web application, you can run:

    python bvp/run-local.py
    
Note that in a production context, you'd not run a script but hand the `app` object to a WSGI process.


### Tests

You can run automated tests with:

    pytest

With coverage reporting:

    pytest --cov=bvp --cov-config .coveragerc

Also possible:

    python setup.py test

One possible source of failures is that pytest needs to be build with Python>=3.6. Ask which pytest is being used:

    which pytest


## Developing

For developers, please consult the documentation next to the relevant code:

* [General coding tips and maintenance](bvp/README.md)
* [Continuous Integration](ci/README.md)
* [Database management](bvp/data/Readme.md)
* [API development](bvp/api/Readme.md)

