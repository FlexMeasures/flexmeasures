# Installing & Running FlexMeasures


## Install FlexMeasures

Install dependencies and the `flexmeasures` platform itself:

    pip install flexmeasures


## Quickstart: database, one user & one asset


### Make a secret key for sessions and password salts

Set a secret key which is used to sign user sessions and re-salt their passwords. The quickest way is with an environment variable, like this:

   `export "SECRET_KEY=something-secret"`

(on Windows, use `set` instead of `export`)

This suffices for a quick start.

If you want to consistenly use FlexMeasures, we recommend you add this setting to your config file at `~/.flexmeasures.cfg` and use a truly random string. Here is a Pythonic way to generate a good secret key:

    `python -c "import secrets; print(secrets.token_urlsafe())"`


### Preparing the time series database

* Make sure you have a Postgres (Version 9+) database for FlexMeasures to use. See `data/Readme.md` (section "Getting ready to use") for instructions on this.
* Tell `flexmeasures` about it:

    `export SQLALCHEMY_DATABASE_URI='postgresql://<user>:<password>@<host-address>[:<port>]/<db>'`
  
  (on Windows, use `set` instead of `export`)
* Create the Postgres DB structure for FlexMeasures:

    `flexmeasures db upgrade`

This suffices for a quick start.

Note that for a more permanent configuration, you can create your FlexMeasures configuration file at `~/.flexmeasures.cfg` and add this:

    `SQLALCHEMY_DATABASE_URI='postgresql://<user>:<password>@<host-address>[:<port>]/<db>'`


### Configure environment

Set an environment variable to indicate in which environment you are operating (one out of development|testing|staging|production), e.g.:

   `export FLASK_ENV=development`

(on Windows, use `set` instead of `export`)

or:

   `echo "FLASK_ENV=development" >> .env`

Note: The default is `production`, which will not work well on localhost due to SSL issues. 


### Add a user

FlexMeasures is a web-based platform, so we need a user account:

`flexmeasures new-user --username <your-username> --email <your-email-address> --roles=admin`

(this will ask you to set a password for the user)

Giving the first user the `admin` role is probably what you want.


### Add structure

Populate the database with some standard energy asset types:

   `flexmeasures db-populate --structure`


### Run FlexMeasures

It's finally time to start running FlexMeasures:

`flexmeasures run`

(This might print some warnings, see the next section where we go into more detail)

Note: In a production context, you shouldn't run a script - hand the `app` object to a WSGI process, as your platform of choice describes.
Often, that requires a WSGI script. We provide an example WSGI script in [the CI Readme](ci/Readme.md).


### Add your first asset 

Head over to `http://localhost:5000/assets` and add a new asset there.

TODO: [issue 57](https://github.com/SeitaBV/flexmeasures/issues/57) should create a CLI function for this.

Note: You can also use the [`POST /api/v2_0/assets`](https://flexmeasures.readthedocs.io/en/latest/api/v2_0.html#post--api-v2_0-assets) endpoint in the FlexMeasures API to create an asset.

### Add data

You can use the [`POST /api/v2_0/postMeterData`](https://flexmeasures.readthedocs.io/en/latest/api/v2_0.html#post--api-v2_0-postMeterData) endpoint in the FlexMeasures API to send meter data.

TODO: [issue 56](https://github.com/SeitaBV/flexmeasures/issues/56) should create a CLI function for adding a lot of data at once, from a CSV dataset.

Also, you can add forecasts for your meter data with the `db_populate` command, here is an example:

   `flexmeasures db-populate --forecasts --from-date 2020-03-08 --to-date 2020-04-08 --asset-type Asset --asset my-solar-panel `

Note: You can also use the API to send forecast data.


## Other settings, for full functionality

### Set mail settings

For FlexMeasures to be able to send email to users (e.g. for resetting passwords), you need an email account which can do that (e.g. GMail). Set the MAIL_* settings in your configuration, see [the Configuration documentation](Configuration.md).


### Install an LP solver

For planning balancing actions, the FlexMeasures platform uses a linear program solver. Currently that is the Cbc solver. See the `FLEXMEASURES_LP_SOLVER` config setting if you want to change to a different solver.

Installing Cbc can be done on Unix via:

    apt-get install coinor-cbc

(also available in different popular package managers).

We provide a script for installing from source (without requiring `sudo` rights) in [the CI Readme](ci/Readme.md).

More information (e.g. for installing on Windows) on [the Cbc website](https://projects.coin-or.org/Cbc).



### Preparing the job queue database and start workers

To let FlexMeasures queue forecasting and scheduling jobs, install a [Redis](https://redis.io/) server and configure access to it within FlexMeasures' config file (see above). You can find the necessary settings in [the Configuration documentation](Configuration.md).

Then run one worker for each kind of job (in a separate terminal):

    flexmeasures run_worker --queue forecasting
    flexmeasures run_worker --queue scheduling

When the main FlexMeasures process runs (e.g. by `flexmeasures run`), the queues of forecasting and scheduling jobs can be visited at `http://localhost:5000/tasks/forecasting` and `http://localhost:5000/tasks/schedules`, respectively (by admins).

When forecasts and schedules have been generated, they should be visible at `http://localhost:5000/analytics`. You can also access forecasts via the FlexMeasures API at [GET  /api/v2_0/getPrognosis](https://flexmeasures.readthedocs.io/en/latest/api/v2_0.html#get--api-v2_0-getPrognosis), and schedules via [GET  /api/v2_0/getDeviceMessage](https://flexmeasures.readthedocs.io/en/latest/api/v2_0.html#get--api-v2_0-getDeviceMessage). 

