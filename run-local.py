from app import APP, a1vpp_logging_config

"""
Run the A1 VPP application locally.

Best to use in a development setup. A professional web server should be handed the APP object to use in a WSGI context.
"""

DEBUG = True  # if False, Flask-Sslify takes over

if __name__ == '__main__':

    print("Initiating FileHandler logger.")

    a1vpp_logging_config["handlers"]["file"] = {
        "class": "logging.FileHandler",
        "formatter": 'default',
        "level": "WARNING",
        "filename": "a1-vpp-errors.log"
    }

    print("Starting A1 VPP application ...")

    APP.run(debug=DEBUG)