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


### Done.

Now, to start the web application, you can run:

    python bvp/run-local.py
    
Note that in a production context, you'd not run a script but hand the `app` object to a WSGI process.


## Developing

### Tests

You can run automated tests with:

    py.test

Also possible:

    python setup.py test
    
One possible source of failures is that pytest needs to be build with Python>=3.6.


### Auto-formatting

We use [Black](https://github.com/ambv/black) to format our Python code and thus find real problems faster.
`Black` can be installed in your editor, but we also use it as a pre-commit hook. To activate that behaviour, do:

    pip install pre-commit
    pre-commit install

in your virtual environment.

Now each git commit will first run `black --diff` over the files affected by the commit
(`pre-commit` will install `black` into its own structure on the first run).
If `black` proposes to edit any file, the commit is aborted (saying that it "failed"), 
and the proposed changes are printed for you to review.

With `git ls-files -m | grep ".py" | xargs black` you can apply the formatting, 
and make them part of your next commit (`git ls-files` cannot list added files,
so they need to be black-formatted separately).


### Hint: Notebooks

If you edit notebooks, make sure results do not end up in git:

    conda install -c conda-forge nbstripout
    nbstripout --install

(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)


### Hint: Quickstart for development

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

### CI Deployment

Bitbucket pipelines are used for deployment and unit testing. See [documentation](ci/README.md) in CI directory for more information.
