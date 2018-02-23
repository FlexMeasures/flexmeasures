from app import APP, bvp_logging_config

"""
Run the BVP application locally.

Best to use in a development setup. A professional web server should be handed the APP object to use in a WSGI context.
"""

DEBUG = True  # if False, Flask-SSlify kicks in

if __name__ == '__main__':

    print("Initiating FileHandler logger.")

    bvp_logging_config["handlers"]["file"] = {
        "class": "logging.FileHandler",
        "formatter": 'default',
        "level": "WARNING",
        "filename": "bvp-errors.log"
    }

    print("Starting the Balancing Valorisation Platform ...")

    APP.run(debug=DEBUG)