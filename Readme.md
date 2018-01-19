# AI VPP

This is Seita's implementation of the VPP pilot of A1.

## Getting Started

* Install Anaconda for Python3.6+
* Make a virtual environment: `conda create --name a1-venv`
* Activate it: `source activate a1-venv`
* Install dependencies: `conda install flask bokeh pandas xlrd iso8601`
* Add data/20171120_A1-VPP_DesignDataSetR01.xls (Excel sheet provided by A1 to Seita)
  as well as data/German day-ahead prices 20140101-20160630.csv (provided by Seita)
  and data/German charging stations 20150101-20150620.csv (provided by Seita).
  and create the folder data/pickles.
* Run: `python init_data.py` (you only need to do this once)
* Run: `python app.py` to start the web application.


## Notebooks

If you edit notebooks, make sure results do not end up in git:

    conda install -c conda-forge nbstripout
    nbstripout --install

(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)

