.. note:: For newer versions of macOS, port 5000 is in use by default by Control Center. You can turn this off by going to System Preferences > Sharing and untick the "Airplay Receiver" box.
          If you don't want to do this for some reason, you can change the host port in the ``docker run`` command to some other port.
          For example, to set it to port 5001, change ``-p 5000:5000`` in the command to ``-p 5001:5000``.
          If you do this, remember that you will have to go to http://localhost:5001 in your browser when you want to inspect the FlexMeasures UI.
