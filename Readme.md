# Balancing Valorisation Platform (BVP)

This is Seita's implementation of the BVP pilot for A1.

The *Balancing Valorisation Platform (BVP)* is a tool for scheduling balancing actions on behalf of the connected asset owners.
Its purpose is to offer these balancing actions as one aggregated service to energy markets, realising the highest possible value for its users.

## Getting Started

### Make a secret key for sessions:

    mkdir -p /path/to/bvp/instance
    head -c 24 /dev/urandom > /path/to/bvp/instance/secret_key

### Dependencies (using plain pip, see below for Anaconda):
* Make a virtual environment: `python3.6 -m venv bvp-venv` or use a different tool like `mkvirtualenv`.
* Activate it: `source bvp-venv/bin/activate`
* Install the bvp platform:

      python setup.py [develop~install]


Note: python3.6-dev should be installed by apt-get or so and xlrd and fbprophet by pip if you 
are using data initialisation in the old-fashioned way. (xlrd might be needed for a while, let's see)

### Prepare/load data:

* Add meta data: data/assets.json and data/markets.json.
* Add real data: data/20171120_A1-VPP_DesignDataSetR01.xls & (Excel sheet provided by A1 to Seita)
  as well as data/German day-ahead prices 20140101-20160630.csv (provided by Seita)
  and data/German charging stations 20150101-20150620.csv (provided by Seita).
  You probably also need to create the folder data/pickles.
* Run `python scripts/init_timeseries_data.py` (you only need to do this once)
* Run `flask db upgrade` to create the Postgres DB structure.
* Run `flask populate_db_structure` to get assets and user data created.


### Done.

Now you can run `python run-local.py` to start the web application. Note, that in a production context,
you'd not run a script but hand the `app` object to a WSGI process.
You probably will be missing several expected environment variables and configuration settings,
but the app will tell you what to do.


### Dependencies using Anaconda:

* Install Anaconda for Python3.6+
* Make a virtual environment: `conda create --name bvp-venv`
* Activate it: `source activate bvp-venv`
* Install dependencies:

      conda install flask bokeh pandas==0.22.0 iso8601 xlrd inflection humanize Flask-SSLify psycopg2-binary Flask-SQLALchemy Flask-Migrate Flask-Classful Flask-WTF Flask-Security bcrypt
      sudo apt-get install python3.6-dev
      conda install -c conda-forge fbprophet
* Install dependencies for initialising the documentation with automatic screenshots:

      conda install -c anaconda pyqt==5.6.0
* For initialising the documentation on Windows (the [Geckodriver](https://github.com/mozilla/geckodriver/releases) should be on your path):

      conda install selenium==3.9.0
      conda install -c conda-forge awesome-slugify


## Notebooks

If you edit notebooks, make sure results do not end up in git:

    conda install -c conda-forge nbstripout
    nbstripout --install

(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)


## Quickstart for development

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
