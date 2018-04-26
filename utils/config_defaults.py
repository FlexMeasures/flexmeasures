from typing import List

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
    TESTING = False
    CSRF_ENABLED = True

    SQLALCHEMY_DATABASE_URI = None

    MAIL_SERVER = None
    MAIL_PORT = None
    MAIL_USE_TLS = None
    MAIL_USE_SSL = None
    MAIL_USERNAME = None
    MAIL_DEFAULT_SENDER = None  # tuple of name and email address
    MAIL_PASSWORD = None

    SECURITY_REGISTERABLE = False
    SECURITY_LOGIN_USER_TEMPLATE = 'admin/login_user.html'
    SECURITY_FORGOT_PASSWORD_TEMPLATE = 'admin/forgot_password.html'
    SECURITY_RESET_PASSWORD_TEMPLATE = 'admin/reset_password.html'
    SECURITY_PASSWORD_SALT = None
    SECURITY_RECOVERABLE = True
    SECURITY_TRACKABLE = False  # this is more in line with modern privacy law
    SECURITY_UNAUTHORIZED_VIEW = None  # TODO: make an error view that looks okay (maybe could even be informative)

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
        "SECURITY_PASSWORD_SALT"
    ]


class ProductionConfig(Config):
    DEBUG = False


class StagingConfig(Config):
    DEVELOPMENT = True
    DEBUG = True


class DevelopmentConfig(Config):
    DEVELOPMENT = True
    DEBUG = True
    SQLALCHEMY_ECHO = True


class TestingConfig(Config):
    TESTING = True
