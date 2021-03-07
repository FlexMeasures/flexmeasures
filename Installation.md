# Installing & Running FlexMeasures


## Install FlexMeasures

Install dependencies and the `flexmeasures` platform itself:

    pip install flexmeasures


## Quickstart: database, a user & asset

### Preparing the time series database

* Make sure you have a Postgres (Version 9+) database for FlexMeasures to use. See `data/Readme.md` for instructions on this.
* Tell `flexmeasures` about it:
    `export SQLALCHEMY_DATABASE_URI='postgresql://<user>:<password>@<host-address>[:<port>]/<db>'`
  (on Windows, use `set` instead of `export`)
* Create the Postgres DB structure for FlexMeasures:
    `flexmeasures db upgrade`

Note that for a more permanent configuration, you can create your FlexMeasures configuration file at `~/.flexmeasures.cfg`.
TODO: the configuration file can also be in the Flask instance directory.


### Configure environment

Set an env variable to indicate in which environment you are operating (one out of development|testing|staging|production), e.g.:

   `echo "FLASK_ENV=development" >> .env`

or:

   `export FLASK_ENV=production`
   
(on Windows, use `set` instead of `export`)

The default is `production`, which will not work well on localhost due to SSL issues. 


## Make a secret key for sessions

Set a secret key which is used to sign user cookies and re-salt their passwords.

   `echo "SECRET_KEY=something-secret`

(on Windows, use `set` instead of `export`)

We recommend you add this setting to your config file (see above). 


### Add a user

`flexmeasures --username <your-username> --email <your-email-address>`


### Add structure

Populate the database with some standard asset tyes:

   `flexmeasures db_populate --structure`


### Run FlexMeasures

`flexmeasures run`

(This might print some warnings, see the next section where we go into more detail)

Note that in a production context, you shouldn't run a script - hand the `app` object to a WSGI process, as your platform of choice describes.

Often, that requires a WSGI script. We provide an example WSGI script in [the CI Readme](ci/Readme.md).


### Add your first asset 

Head over to `http://localhost:5000/assets` and add a new asset there.

TODO: For this we should also make a CLI function.

Note: You can also use the API to create assets (e.g. through a script or a custom frontend application, see our API documentation).

### Add data

TODO: issue 56 should create a CLI function for this.

Note: You can also use the API to send meter dat.a

You can add forecasts for your meter data with the `db_populate` command, here is an example:
   
   `flexmeasures db_populate --forecasts --from-date 2020-03-08 --to-date 2020-04-08 --asset-type Asset --asset my-solar-panel `

Note: You can also use the API to send forecast data.


## Other settings for full functionality

### Set mail settings

For FlexMeasures to be able to send email to users (e.g. for resetting passwords), set MAIL_* settings. `flexmeasures run` should tell you which ones you need.


### Preparing the job queue database

To let FlexMeasures queue forecasting and scheduling jobs, install a Redis server and configure access to it within FlexMeasures' config file (see above). You can find the default settings in `flexmeasures/utils/config_defaults.py`.

TODO: more detail


### Install an LP solver

For planning balancing actions, the flexmeasures platform uses a linear program solver. Currently that is the Cbc solver. See the `FLEXMEASURES_LP_SOLVER` config setting if you want to change to a different solver.

Installing Cbc can be done on Unix via:

    apt-get install coinor-cbc

(also available in different popular package managers).

We provide a script for installing from source (without requiring `sudo` rights) in [the CI Readme](ci/Readme.md).

More information (e.g. for installing on Windows) on [the website](https://projects.coin-or.org/Cbc).




