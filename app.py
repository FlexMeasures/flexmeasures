import logging
from logging import FileHandler, Formatter
from logging.handlers import RotatingFileHandler

from flask import Flask

from views import a1_views
from error_views import a1_error_views


DEBUG=False

APP = Flask(__name__)
APP.register_blueprint(a1_views)
APP.register_blueprint(a1_error_views)



def get_logfile_handler():
    if DEBUG:
        print("Initiating FileHandler logger.")
        file_handler = FileHandler(filename="a1-vpp-errors.log")
    else:
        print("Initiating RotatingFileHandler logger.")
        file_handler = RotatingFileHandler(filename="a1-vpp-errors.log")
    file_handler.setFormatter(Formatter(
        '%(asctime)s %(levelname)s: %(message)s '
        '[in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.WARNING)
    return file_handler


if __name__ == '__main__':
    print("Starting A1 VPP application ...")

    APP.logger.addHandler(get_logfile_handler())

    APP.run(debug=DEBUG)
