import logging
from logging import FileHandler, Formatter
from logging.handlers import RotatingFileHandler

from flask import Flask
from werkzeug.exceptions import BadRequest, HTTPException, NotFound

from views import a1_views


DEBUG=True

APP = Flask(__name__)
APP.register_blueprint(a1_views)


@APP.errorhandler(HTTPException)
def handle_http_exception(e):
    print("Handling http exception")
    return str(e), 500  # TODO: make nicer error page

@APP.errorhandler(BadRequest)
def handle_bad_request(e):
    print("Handling bad request")
    return str(e), 400  # TODO: make nicer error page

@APP.errorhandler(NotFound)
def handle_not_found(e):
    return str(e), 404  # TODO: make nicer error page


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
