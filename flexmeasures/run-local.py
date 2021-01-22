from flexmeasures.app import create as create_app
from flexmeasures.utils import config_defaults

"""
Run the FlexMeasures application locally.

Best to use in a development setup. A professional web server should be handed the app object to use in a WSGI context.
"""

if __name__ == "__main__":

    print("Starting the FlexMeasures Platform ...")

    create_app().run(debug=config_defaults.DevelopmentConfig.DEBUG, load_dotenv=False)
