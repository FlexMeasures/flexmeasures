"""Flask-Security forms of FlexMeasures."""

from flask_security.forms import LoginForm

from flexmeasures.auth.event_logging import email_fingerprint, log_authentication_event


class FlexMeasuresLoginForm(LoginForm):
    """Log failed logins which Flask-Security does not report as a failed authentication of a known user."""

    def validate(self, **kwargs) -> bool:
        if super().validate(**kwargs):
            return True
        user = getattr(self, "user", None)
        email = self.email.data if getattr(self, "email", None) is not None else None
        if user is None and email:
            log_authentication_event(
                f"failed login for an unknown email address (hash {email_fingerprint(email)})",
                failed=True,
            )
        elif user is not None and getattr(self, "user_authenticated", False):
            # The password was right, but the user may not log in (e.g. deactivated)
            log_authentication_event(
                f"refused login for user {user.id} with a correct password (active: {user.active})",
                failed=True,
            )
        # Wrong passwords of known users are logged through Flask-Security's user_failed_authn signal
        return False
