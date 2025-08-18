.. note:: For newer versions of macOS, port 5000 is in use by default by Control Center.
          You can turn this off by going to System Preferences > Sharing and untick the "Airplay Receiver" box.
          If you don't want to do this for some reason, you can change the port for locally running FlexMeasures by setting the ``FLASK_RUN_PORT`` environment variable.
          For example, to set it to port 5001:

          .. code-block:: bash

              $ export FLASK_RUN_PORT=5001  # You can also add this to your local .env

          If you do this, remember that you will have to go to http://localhost:5001 in your browser when you want to inspect the FlexMeasures UI.
