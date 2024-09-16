"""
Our configuration requirements and defaults

This can be adjusted per environment here.
Anything confidential should be handled outside of source control (e.g. a SECRET KEY file is generated on first install,
and confidential settings can be set via the <app-env>-conf.py file.
"""

from __future__ import annotations

from datetime import timedelta
import logging


class Config(object):
    """
    If there is a useful default value, set it here.
    Otherwise, set to None, so that it can be set either by subclasses or the env-specific config script.
    """

    DEBUG: bool = False
    LOGGING_LEVEL: int = logging.WARNING
    SECRET_KEY: str | None = None

    FLEXMEASURES_ENV_DEFAULT = "production"

    SQLALCHEMY_DATABASE_URI: str | None = None
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

    MAIL_SERVER: str | None = "localhost"
    MAIL_PORT: int | None = 25
    MAIL_USE_TLS: bool | None = False
    MAIL_USE_SSL: bool | None = False
    MAIL_USERNAME: str | None = None
    MAIL_DEFAULT_SENDER = (
        "FlexMeasures",
        "no-reply@example.com",
    )  # tuple of name and email address
    MAIL_PASSWORD: str | None = None

    SECURITY_REGISTERABLE: bool = False
    SECURITY_LOGIN_USER_TEMPLATE: str = "admin/login_user.html"
    SECURITY_EMAIL_SUBJECT_PASSWORD_RESET: str = (
        "Password reset instructions for your FlexMeasures account."
    )
    SECURITY_EMAIL_SUBJECT_PASSWORD_NOTICE: str = (
        "Your FlexMeasures password has been reset."
    )
    SECURITY_FORGOT_PASSWORD_TEMPLATE: str = "admin/forgot_password.html"
    SECURITY_RECOVERABLE: bool = True
    SECURITY_RESET_PASSWORD_TEMPLATE: str = "admin/reset_password.html"
    SECURITY_TOKEN_AUTHENTICATION_HEADER: str = "Authorization"
    SECURITY_TOKEN_MAX_AGE: int = 60 * 60 * 6  # six hours
    SECURITY_TRACKABLE: bool = False  # this is more in line with modern privacy law
    SECURITY_PASSWORD_SALT: str | None = None

    # Allowed cross-origins. Set to "*" to allow all. For development (e.g. javascript on localhost) you might use "null" here
    CORS_ORIGINS: list[str] | str = []
    # this can be a dict with all possible options as value per regex, see https://flask-cors.readthedocs.io/en/latest/configuration.html
    CORS_RESOURCES: dict | list | str = [r"/api/*"]
    CORS_SUPPORTS_CREDENTIALS: bool = True

    MAPBOX_ACCESS_TOKEN: str | None = None

    RQ_DASHBOARD_POLL_INTERVAL: int = (
        3000  # Web interface poll period for updates in ms
    )

    SENTRY_DSN: str | None = None
    # Place additional Sentry config here.
    # traces_sample_rate is for performance monitoring across all transactions,
    # you probably want to adjust this.
    FLEXMEASURES_SENTRY_CONFIG: dict = dict(traces_sample_rate=0.33)
    FLEXMEASURES_MONITORING_MAIL_RECIPIENTS: list[str] = []

    FLEXMEASURES_PLATFORM_NAME: str | list[str | tuple[str, list[str]]] = "FlexMeasures"
    FLEXMEASURES_MODE: str = ""
    FLEXMEASURES_ALLOW_DATA_OVERWRITE: bool = False
    FLEXMEASURES_TIMEZONE: str = "Asia/Seoul"
    FLEXMEASURES_HIDE_NAN_IN_UI: bool = False
    FLEXMEASURES_PUBLIC_DEMO_CREDENTIALS: tuple | None = None
    # Configuration used for entity addressing:
    # This setting contains the domain on which FlexMeasures runs
    # and the first month when the domain was under the current owner's administration
    FLEXMEASURES_HOSTS_AND_AUTH_START: dict[str, str] = {"flexmeasures.io": "2021-01"}
    FLEXMEASURES_PLUGINS: list[str] | str = []  # str will be checked for commas
    FLEXMEASURES_PROFILE_REQUESTS: bool = False
    FLEXMEASURES_DB_BACKUP_PATH: str = "migrations/dumps"
    FLEXMEASURES_MENU_LOGO_PATH: str = ""
    FLEXMEASURES_EXTRA_CSS_PATH: str = ""
    FLEXMEASURES_ROOT_VIEW: str | list[str | tuple[str, list[str]]] = []
    FLEXMEASURES_MENU_LISTED_VIEWS: list[str | tuple[str, list[str]]] = [
        "dashboard",
    ]
    FLEXMEASURES_MENU_LISTED_VIEW_ICONS: dict[str, str] = {}
    FLEXMEASURES_MENU_LISTED_VIEW_TITLES: dict[str, str] = {}
    FLEXMEASURES_ASSET_TYPE_GROUPS = {
        "renewables": ["solar", "wind"],
        "EVSE": ["one-way_evse", "two-way_evse"],
    }  # how to group assets by asset types
    FLEXMEASURES_LP_SOLVER: str = "appsi_highs"
    FLEXMEASURES_JOB_TTL: timedelta = timedelta(days=1)
    FLEXMEASURES_PLANNING_HORIZON: timedelta = timedelta(days=2)
    FLEXMEASURES_MAX_PLANNING_HORIZON: timedelta | int | None = 2520  # smallest number divisible by 1-10, which yields pleasant-looking durations for common sensor resolutions
    FLEXMEASURES_PLANNING_TTL: timedelta = timedelta(
        days=7
    )  # Time to live for UDI event ids of successful scheduling jobs. Set a negative timedelta to persist forever.
    FLEXMEASURES_DEFAULT_DATASOURCE: str = "FlexMeasures"
    FLEXMEASURES_JOB_CACHE_TTL: int = 3600  # Time to live for the job caching keys in seconds. Set a negative timedelta to persist forever.
    FLEXMEASURES_TASK_CHECK_AUTH_TOKEN: str | None = None
    FLEXMEASURES_REDIS_URL: str = "localhost"
    FLEXMEASURES_REDIS_PORT: int = 6379
    FLEXMEASURES_REDIS_DB_NR: int = 0  # Redis per default has 16 databases, [0-15]
    FLEXMEASURES_REDIS_PASSWORD: str | None = None
    FLEXMEASURES_JS_VERSIONS: dict = dict(
        vega="5.22.1",
        vegaembed="6.21.0",
        vegalite="5.5.0",  # "5.6.0" has a problematic bar chart: see our sensor page and https://github.com/vega/vega-lite/issues/8496
        currencysymbolmap="5.1.0",
        # todo: expand with other js versions used in FlexMeasures
    )
    FLEXMEASURES_JSON_COMPACT = False

    FLEXMEASURES_FALLBACK_REDIRECT: bool = False

    # Custom sunset switches
    FLEXMEASURES_API_SUNSET_ACTIVE: bool = False  # if True, sunset endpoints return 410 (Gone) responses; if False, they return 404 (Not Found) responses or will work as before, depending on whether the current FlexMeasures version still contains the endpoint logic
    FLEXMEASURES_API_SUNSET_DATE: str | None = None  # e.g. 2023-05-01
    FLEXMEASURES_API_SUNSET_LINK: str | None = None  # e.g. https://flexmeasures.readthedocs.io/en/latest/api/introduction.html#deprecation-and-sunset

    # if True, all requests are forced to be via HTTPS.
    FLEXMEASURES_FORCE_HTTPS: bool = False
    # if True, the content could be accessed via HTTPS.
    FLEXMEASURES_ENFORCE_SECURE_CONTENT_POLICY: bool = False


#  names of settings which cannot be None
#  SECRET_KEY is also required but utils.app_utils.set_secret_key takes care of this better.
required: list[str] = ["SQLALCHEMY_DATABASE_URI"]

#  settings whose absence should trigger a warning
mail_warning = "Without complete mail settings, FlexMeasures will not be able to send mails to users, e.g. for password resets!"
redis_warning = "Without complete redis connection settings, FlexMeasures will not be able to run forecasting and scheduling job queues."
warnable: dict[str, str] = {
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
    DEBUG: bool = False
    LOGGING_LEVEL: int = logging.ERROR


class StagingConfig(Config):
    DEBUG: bool = False
    LOGGING_LEVEL: int = logging.WARNING


class DevelopmentConfig(Config):
    DEBUG: bool = True
    LOGGING_LEVEL: int = logging.DEBUG
    SQLALCHEMY_ECHO: bool = False
    PROPAGATE_EXCEPTIONS: bool = True
    # PRESERVE_CONTEXT_ON_EXCEPTION: bool = False  # might need this to make our transaction handling work in debug mode
    FLEXMEASURES_MODE: str = "development"
    FLEXMEASURES_PROFILE_REQUESTS: bool = True
    FLEXMEASURES_JSON_COMPACT = False


class TestingConfig(Config):
    DEBUG: bool = True  # this seems to be important for logging in, not sure why
    LOGGING_LEVEL: int = logging.INFO
    WTF_CSRF_ENABLED: bool = False  # also necessary for logging in during tests

    SECRET_KEY: str = "dummy-key-for-testing"
    SECURITY_PASSWORD_SALT: str = "$2b$19$abcdefghijklmnopqrstuv"
    SQLALCHEMY_DATABASE_URI: str = (
        "postgresql://flexmeasures_test:flexmeasures_test@localhost/flexmeasures_test"
    )
    # SQLALCHEMY_ECHO = True
    FLEXMEASURES_TASK_CHECK_AUTH_TOKEN: str = "test-task-check-token"

    # These can speed up tests due to less hashing work (I saw ~165s -> ~100s)
    # (via https://github.com/mattupstate/flask-security/issues/731#issuecomment-362186021)
    SECURITY_HASHING_SCHEMES: list[str] = ["hex_md5"]
    SECURITY_DEPRECATED_HASHING_SCHEMES: list[str] = []
    FLEXMEASURES_MODE: str = "test"
    FLEXMEASURES_PLANNING_HORIZON: timedelta = timedelta(
        hours=2 * 24
    )  # if more than 2 days, consider setting up more days of price data for tests


class DocumentationConfig(Config):
    SECRET_KEY: str = "dummy-key-for-documentation"
    SQLALCHEMY_DATABASE_URI: str = "postgresql://dummy:uri@for/documentation"
