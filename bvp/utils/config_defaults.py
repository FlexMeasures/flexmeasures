from datetime import timedelta
import logging
from typing import List, Optional

"""
This lays out our configuration requirements and allows to set trivial defaults, per environment adjustable.
Anything confidential should be handled outside of source control (e.g. a SECRET KEY file is generated on first install,
and confidential settings can be set via the <app-env>-conf.py file.
"""


class Config(object):
    """
    If there is a useful default value, set it here.
    Otherwise, set to None, so that it can be set either by subclasses or the env-specific config script.
    """

    DEBUG = False
    LOGGING_LEVEL = logging.WARNING
    CSRF_ENABLED = True

    SQLALCHEMY_DATABASE_URI: Optional[str] = None
    # https://stackoverflow.com/questions/33738467/how-do-i-know-if-i-can-disable-sqlalchemy-track-modifications
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 299,  # https://www.pythonanywhere.com/forums/topic/2599/
        # "pool_timeout": 20,
        "pool_pre_ping": True,  # https://docs.sqlalchemy.org/en/13/core/pooling.html#disconnect-handling-pessimistic
    }

    MAIL_SERVER: Optional[str] = None
    MAIL_PORT: Optional[str] = None
    MAIL_USE_TLS: Optional[str] = None
    MAIL_USE_SSL: Optional[str] = None
    MAIL_USERNAME: Optional[str] = None
    MAIL_DEFAULT_SENDER = (
        "bvp",
        "no-reply@example.com",
    )  # tuple of name and email address
    MAIL_PASSWORD: Optional[str] = None

    SECURITY_REGISTERABLE = False
    SECURITY_LOGIN_USER_TEMPLATE = "admin/login_user.html"
    SECURITY_FORGOT_PASSWORD_TEMPLATE = "admin/forgot_password.html"
    SECURITY_RESET_PASSWORD_TEMPLATE = "admin/reset_password.html"
    SECURITY_RECOVERABLE = True
    SECURITY_TOKEN_AUTHENTICATION_HEADER = "Authorization"
    SECURITY_TOKEN_MAX_AGE = 60 * 60 * 6  # six hours
    SECURITY_TRACKABLE = False  # this is more in line with modern privacy law
    SECURITY_PASSWORD_SALT: Optional[str] = None

    DARK_SKY_API_KEY: Optional[str] = None

    JSONIFY_PRETTYPRINT_REGULAR = False

    BVP_MODE = ""
    BVP_API = False
    BVP_PUBLIC_DEMO = False
    BVP_TIMEZONE = "Asia/Seoul"
    BVP_HIDE_NAN_IN_UI = False
    BVP_DEMO_YEAR = 2015
    BVP_DB_BACKUP_PATH = "migrations/dumps"
    BVP_LP_SOLVER = "cbc"
    BVP_PLANNING_HORIZON = timedelta(hours=2 * 24)
    BVP_PLANNING_TTL = timedelta(
        days=7
    )  # Time to live for UDI event ids of successful scheduling jobs. Set a negative timedelta to persist forever.
    BVP_TASK_CHECK_AUTH_TOKEN: Optional[str] = None
    BVP_PA_DOMAIN_NAMES: List[str] = []
    BVP_REDIS_URL = "localhost"
    BVP_REDIS_PORT = 6379
    BVP_REDIS_DB_NR = 0  # Redis per default has 16 databases, [0-15]
    BVP_REDIS_PASSWORD = None

    #  names of settings which cannot be None
    required: List[str] = [
        "SQLALCHEMY_DATABASE_URI",
        "MAIL_SERVER",
        "MAIL_PORT",
        "MAIL_USE_TLS",
        "MAIL_USE_SSL",
        "MAIL_USERNAME",
        "MAIL_DEFAULT_SENDER",
        "MAIL_PASSWORD",
        "SECURITY_PASSWORD_SALT",
    ]


class ProductionConfig(Config):
    DEBUG = False
    LOGGING_LEVEL = logging.ERROR


class StagingConfig(Config):
    DEBUG = False
    LOGGING_LEVEL = logging.WARNING


class DevelopmentConfig(Config):
    DEBUG = True
    LOGGING_LEVEL = logging.DEBUG
    SQLALCHEMY_ECHO = False
    PROPAGATE_EXCEPTIONS = True
    # PRESERVE_CONTEXT_ON_EXCEPTION = False  # might need this to make our transaction handling work in debug mode
    JSONIFY_PRETTYPRINT_REGULAR = True
    SERVER_NAME = "localhost:5000"
    BVP_MODE = "development"


class TestingConfig(Config):
    DEBUG = True  # this seems to be important for logging in, not sure why
    LOGGING_LEVEL = logging.INFO
    WTF_CSRF_ENABLED = False  # also necessary for logging in during tests

    SECURITY_PASSWORD_SALT = "$2b$19$abcdefghijklmnopqrstuv"
    SQLALCHEMY_DATABASE_URI = "postgresql://a1test:a1test@127.0.0.1/a1test"
    # SQLALCHEMY_ECHO = True
    BVP_TASK_CHECK_AUTH_TOKEN = "test-task-check-token"

    # These can speed up tests due to less hashing work (I saw ~165s -> ~100s)
    # (via https://github.com/mattupstate/flask-security/issues/731#issuecomment-362186021)
    SECURITY_HASHING_SCHEMES = ["hex_md5"]
    SECURITY_DEPRECATED_HASHING_SCHEMES: List[str] = []
    BVP_MODE = "test"
    BVP_API = True
    BVP_PLANNING_HORIZON = timedelta(
        hours=2 * 24
    )  # if more than 2 days, consider setting up more days of price data for tests
