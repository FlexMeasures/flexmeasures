from datetime import timedelta
import logging
from typing import List, Optional, Union, Dict, Tuple

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

    DEBUG: bool = False
    LOGGING_LEVEL: int = logging.WARNING
    SECRET_KEY: Optional[str] = None

    SQLALCHEMY_DATABASE_URI: Optional[str] = None
    # https://stackoverflow.com/questions/33738467/how-do-i-know-if-i-can-disable-sqlalchemy-track-modifications
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_recycle": 299,  # https://www.pythonanywhere.com/forums/topic/2599/
        # "pool_timeout": 20,
        "pool_pre_ping": True,  # https://docs.sqlalchemy.org/en/13/core/pooling.html#disconnect-handling-pessimistic
        "connect_args": {
            "options": "-c timezone=utc"
        },  # https://stackoverflow.com/a/59932909/13775459
    }

    MAIL_SERVER: Optional[str] = "localhost"
    MAIL_PORT: Optional[int] = 25
    MAIL_USE_TLS: Optional[bool] = False
    MAIL_USE_SSL: Optional[bool] = False
    MAIL_USERNAME: Optional[str] = None
    MAIL_DEFAULT_SENDER = (
        "FlexMeasures",
        "no-reply@example.com",
    )  # tuple of name and email address
    MAIL_PASSWORD: Optional[str] = None

    SECURITY_REGISTERABLE = False
    SECURITY_LOGIN_USER_TEMPLATE = "admin/login_user.html"
    SECURITY_EMAIL_SUBJECT_PASSWORD_RESET = (
        "Password reset instructions for your FlexMeasures account."
    )
    SECURITY_EMAIL_SUBJECT_PASSWORD_NOTICE = (
        "Your FlexMeasures password has been reset."
    )
    SECURITY_FORGOT_PASSWORD_TEMPLATE = "admin/forgot_password.html"
    SECURITY_RECOVERABLE = True
    SECURITY_RESET_PASSWORD_TEMPLATE = "admin/reset_password.html"
    SECURITY_RECOVERABLE = True
    SECURITY_TOKEN_AUTHENTICATION_HEADER = "Authorization"
    SECURITY_TOKEN_MAX_AGE = 60 * 60 * 6  # six hours
    SECURITY_TRACKABLE = False  # this is more in line with modern privacy law
    SECURITY_PASSWORD_SALT: Optional[str] = None

    # Allowed cross-origins. Set to "*" to allow all. For development (e.g. javascript on localhost) you might use "null" here
    CORS_ORIGINS: Union[List[str], str] = []
    # this can be a dict with all possible options as value per regex, see https://flask-cors.readthedocs.io/en/latest/configuration.html
    CORS_RESOURCES: Union[dict, list, str] = [r"/api/*"]
    CORS_SUPPORTS_CREDENTIALS: bool = True

    DARK_SKY_API_KEY: Optional[str] = None

    MAPBOX_ACCESS_TOKEN: Optional[str] = None

    JSONIFY_PRETTYPRINT_REGULAR: bool = False

    RQ_DASHBOARD_POLL_INTERVAL: int = (
        3000  # Web interface poll period for updates in ms
    )

    FLEXMEASURES_PLATFORM_NAME: str = "FlexMeasures"
    FLEXMEASURES_MODE: str = ""
    FLEXMEASURES_TIMEZONE: str = "Asia/Seoul"
    FLEXMEASURES_SHOW_CONTROL_UI: bool = False
    FLEXMEASURES_HIDE_NAN_IN_UI: bool = False
    FLEXMEASURES_PUBLIC_DEMO_CREDENTIALS: Optional[Tuple] = None
    FLEXMEASURES_DEMO_YEAR: Optional[int] = None
    # Configuration used for entity addressing:
    # This setting contains the domain on which FlexMeasures runs
    # and the first month when the domain was under the current owner's administration
    FLEXMEASURES_HOSTS_AND_AUTH_START: dict = {"flexmeasures.io": "2021-01"}
    FLEXMEASURES_PROFILE_REQUESTS: bool = False
    FLEXMEASURES_DB_BACKUP_PATH: str = "migrations/dumps"
    FLEXMEASURES_LP_SOLVER: str = "cbc"
    FLEXMEASURES_PLANNING_HORIZON: timedelta = timedelta(hours=2 * 24)
    FLEXMEASURES_PLANNING_TTL: timedelta = timedelta(
        days=7
    )  # Time to live for UDI event ids of successful scheduling jobs. Set a negative timedelta to persist forever.
    FLEXMEASURES_TASK_CHECK_AUTH_TOKEN: Optional[str] = None
    FLEXMEASURES_REDIS_URL: str = "localhost"
    FLEXMEASURES_REDIS_PORT: int = 6379
    FLEXMEASURES_REDIS_DB_NR: int = 0  # Redis per default has 16 databases, [0-15]
    FLEXMEASURES_REDIS_PASSWORD: Optional[str] = None


#  names of settings which cannot be None
#  SECRET_KEY is also required but utils.app_utils.set_secret_key takes care of this better.
required: List[str] = ["SQLALCHEMY_DATABASE_URI"]

#  settings whose absence should trigger a warning
mail_warning = "Without complete mail settings, FlexMeasures will not be able to send mails to users, e.g. for password resets!"
redis_warning = "Without complete redis connection settings, FlexMeasures will not be able to run forecasting and scheduling job queues."
warnable: Dict[str, str] = {
    "MAIL_SERVER": mail_warning,
    "MAIL_PORT": mail_warning,
    "MAIL_USE_TLS": mail_warning,
    "MAIL_USE_SSL": mail_warning,
    "MAIL_USERNAME": mail_warning,
    "MAIL_DEFAULT_SENDER": mail_warning,
    "MAIL_PASSWORD": mail_warning,
    "FLEXMEASURES_REDIS_URL": redis_warning,
    "FLEXMEASURES_REDIS_PORT": redis_warning,
    "FLEXMEASURES_REDIS_DB_NR": redis_warning,
    "FLEXMEASURES_REDIS_PASSWORD": redis_warning,
}


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
    FLEXMEASURES_MODE = "development"
    FLEXMEASURES_PROFILE_REQUESTS: bool = True


class TestingConfig(Config):
    DEBUG = True  # this seems to be important for logging in, not sure why
    LOGGING_LEVEL = logging.INFO
    WTF_CSRF_ENABLED = False  # also necessary for logging in during tests

    SECURITY_PASSWORD_SALT = "$2b$19$abcdefghijklmnopqrstuv"
    SQLALCHEMY_DATABASE_URI = (
        "postgresql://flexmeasures_test:flexmeasures_test@localhost/flexmeasures_test"
    )
    # SQLALCHEMY_ECHO = True
    FLEXMEASURES_TASK_CHECK_AUTH_TOKEN = "test-task-check-token"

    # These can speed up tests due to less hashing work (I saw ~165s -> ~100s)
    # (via https://github.com/mattupstate/flask-security/issues/731#issuecomment-362186021)
    SECURITY_HASHING_SCHEMES = ["hex_md5"]
    SECURITY_DEPRECATED_HASHING_SCHEMES: List[str] = []
    FLEXMEASURES_MODE = "test"
    FLEXMEASURES_PLANNING_HORIZON = timedelta(
        hours=2 * 24
    )  # if more than 2 days, consider setting up more days of price data for tests


class DocumentationConfig(Config):
    pass
