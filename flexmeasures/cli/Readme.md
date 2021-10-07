# Command line interface tasks

As part of the backend server functionality, FlexMeasures includes commands to work on the database through python scripts.
These scripts are made available as cli tasks.

To view the available commands, run:

    flexmeasures --help  

For help on individual commands, type `flexmesaures <command> --help`.
Structural data refers to database tables which do not contain time series data.

To create new commands, be sure to register any new file (containing the corresponding script) with the flexmeasures CLI in `flexmeasures/cli/__init__.py`.
