# AI VPP

This is Seita's implementation of the VPP pilot of A1.

## Getting Started

### Make a secret key for sessions:

    mkdir -p /path/to/a1-vpp/instance
    head -c 24 /dev/urandom > /path/to/a1-vpp/instance/secret_key

### Dependencies using Anaconda:
* Install Anaconda for Python3.6+
* Make a virtual environment: `conda create --name a1-venv`
* Activate it: `source activate a1-venv`
* Install dependencies:

      conda install flask bokeh pandas==0.22.0 iso8601 xlrd 
      conda install -c conda-forge fbprophet

### Dependencies using plain pip:
* Make a virtual environment: `python3.6 -m venv a1-venv` or use a different tool like `mkvirtualenv`.
* Activate it: `source a1-venv/bin/activate`
* Install dependencies:

      sudo apt-get install python3.6-dev
      pip install flask bokeh pandas==0.22.0 iso8601 xlrd fbprophet


Note: python3.6-dev, xlrd and fbprophet are used for initialising data only.

### Prepare/load data:

* Add data/20171120_A1-VPP_DesignDataSetR01.xls (Excel sheet provided by A1 to Seita)
  as well as data/German day-ahead prices 20140101-20160630.csv (provided by Seita)
  and data/German charging stations 20150101-20150620.csv (provided by Seita).
  and create the folder data/pickles.
* Run: `python init_data.py` (you only need to do this once)


### Done.

Now you can run `python app.py` to start the web application.


## Notebooks

If you edit notebooks, make sure results do not end up in git:

    conda install -c conda-forge nbstripout
    nbstripout --install

(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)

