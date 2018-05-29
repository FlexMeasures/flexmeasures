from bvp.app import create as create_app
from bvp.utils.config_utils import bvp_logging_config
from bvp.utils import config_defaults

"""
Run the BVP application locally.

Best to use in a development setup. A professional web server should be handed the app object to use in a WSGI context.
"""

if __name__ == "__main__":

    print("Initiating FileHandler logger.")

    bvp_logging_config["handlers"]["file"] = {
        "class": "logging.FileHandler",
        "formatter": "default",
        "level": "WARNING",
        "filename": "bvp-errors.log",
    }

    print("Starting the Balancing Valorisation Platform ...")

    create_app().run(debug=config_defaults.DevelopmentConfig.DEBUG, load_dotenv=False)
