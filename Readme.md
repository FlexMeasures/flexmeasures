# AI VPP

This is Seita's implementaiton of the VPP pilot of A1.

## Getting Started

* Install Anaconda for Python3.6+
* Make a virtual environment: `conda create --name a1-venv`
* Activate it: `source activate a1-venv`
* Install dependencies: `conda install flask bokeh pandas iso8601`
* Add data/pv.csv (PV consumption data provided by A1 to Seita)
* Run: `python app.py`


## Notebooks

If you edit notebooks, make sure results do not end up in git:

    conda install -c conda-forge nbstripout
    nbstripout --install

(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)

