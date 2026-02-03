import importlib
import pkgutil
from flask import Blueprint, current_app
from flask_security import auth_token_required

from flask_sock import Sock

sock = Sock()


def import_all_modules(package_name):
    package = importlib.import_module(package_name)
    for _, name, _ in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package_name}.{name}")


# we need to import all the modules to run the route decorators
import_all_modules("flexmeasures.ws")
