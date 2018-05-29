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
  an [Anaconda distribution](https://conda.io/docs/user-guide/tasks/manage-environments.html) as base.
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

    psql -U {user_name} -d {database_name} -f {file_path} -h {host_name}
    
Else, you can populate some standard data, most of which comes from files:

* For meta data, ask someone for `data/assets.json`
* For time series data: 
  - Either ask someone for pickled dataframes, to be put in `data/pickles`
  - Or add get them from the source:
     - Ask someone for `data/20171120_A1-VPP_DesignDataSetR01.xls` (Excel sheet provided by A1 to Seita),
       `data/German day-ahead prices 20140101-20160630.csv` (provided by Seita)
       and `data/German charging stations 20150101-20150620.csv` (provided by Seita).
       You probably also need to create the folder data/pickles.
    - Install `python3.6-dev` by apt-get or so, as well as `xlrd` and `fbprophet` by pip.
    - Run `python bvp/scripts/init_timeseries_data.py`
* Run `flask db_populate --time-series-data` to get data, including time series data created.


### Done.

Now, to start the web application, you can run:

    python bvp/run-local.py
    
Note that in a production context, you'd not run a script but hand the `app` object to a WSGI process.



## Hint: Notebooks

If you edit notebooks, make sure results do not end up in git:

    conda install -c conda-forge nbstripout
    nbstripout --install

(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)


## Hint: Quickstart for development

I added this to my ~/.bashrc, so I only need to type `bvp` to get started (all paths depend on your local environment, of course):

    addssh(){
        eval `ssh-agent -s`
        ssh-add ~/.ssh/id_bitbucket
    }
    bvp(){
        addssh
        cd ~/bvp  
        git pull  # do not use if any production-like app runs from the git code                                                                                                                                                                     
        workon bvp-venv  # this depends on how you created your virtual environment
    }
