# Command line interface tasks

As part of the backend server functionality, FlexMeasures includes commands to work on the database through python scripts.
These scripts are made available as cli tasks.

To view the available commands, run:

    flask --help  

For help on individual commands, for example on the saving and loading functionality, type `flask db-save --help` or `flask db-load --help`.
These help messages are generated from the code (see the file db_pop.py in the cli_tasks directory).
Structural data refers to database tables with relatively little entries (they describe things like assets, markets and weather sensors).
Time series data refers to database tables with many entries (like power, price and temperature values).
The default location for storing database backups is within the top-level `migrations` directory.
The contents of this folder are not part of the code repository, and database backups will be lost when deleted.

The load functionality is also made available as an API endpoint called _restoreData_, and described as such in the user documentation for the play server.
The relevant API endpoint is set up in the `flexmeasures/api/play` directory.
The file `routes.py` contains its registration and documentation, while the file `implementations.py` contains the functional logic that connects the API endpoint to the same scripts that are accessible through the command line interface.

The save functionality is currently not available as an API endpoint.
This script cannot be executed within the lifetime of an https request, and would require processing within a separate thread, similar to how forecasting jobs are handled by FlexMeasures.

To create new commands, be sure to register any new file (containing the corresponding script) with the flask cli in `flexmeasures/data/__init__.py`.
