# Balancing Valorisation Platform (BVP)

This is Seita's implementation of the BVP pilot for A1.

## Getting Started

### Make a secret key for sessions:

    mkdir -p /path/to/bvp/instance
    head -c 24 /dev/urandom > /path/to/bvp/instance/secret_key

### Dependencies using Anaconda:
* Install Anaconda for Python3.6+
* Make a virtual environment: `conda create --name bvp-venv`
* Activate it: `source activate bvp-venv`
* Install dependencies:

      conda install flask bokeh pandas==0.22.0 iso8601 xlrd inflection humanize Flask-SSLify 
      conda install -c conda-forge fbprophet
* Install dependencies for initialising the documentation with automatic screenshots:

      conda install -c anaconda pyqt==5.6.0
* Or for initialising the documentation on Windows (the [Geckodriver](https://github.com/mozilla/geckodriver/releases) should be on your path):

      conda install selenium==3.9.0
      conda install -c conda-forge awesome-slugify

### Dependencies using plain pip:
* Make a virtual environment: `python3.6 -m venv bvp-venv` or use a different tool like `mkvirtualenv`.
* Activate it: `source bvp-venv/bin/activate`
* Install dependencies:

      sudo apt-get install python3.6-dev
      pip install flask bokeh pandas==0.22.0 iso8601 xlrd inflection humanize Flask-SSLify fbprophet


Note: python3.6-dev, xlrd and fbprophet are used for initialising data only.

### Prepare/load data:

* Add meta data: data/assets.json and data/markets.json.
* Add real data: data/20171120_A1-VPP_DesignDataSetR01.xls & (Excel sheet provided by A1 to Seita)
  as well as data/German day-ahead prices 20140101-20160630.csv (provided by Seita)
  and data/German charging stations 20150101-20150620.csv (provided by Seita).
  You probably also need to create the folder data/pickles.
* Run: `python init_data.py` (you only need to do this once)


### Done.

Now you can run `python app.py` to start the web application.


## Notebooks

If you edit notebooks, make sure results do not end up in git:

    conda install -c conda-forge nbstripout
    nbstripout --install

(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)

