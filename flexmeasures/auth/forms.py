"""Flask-Security forms that respect self-service password grants."""

from flask_security import current_user
from flask_security.forms import ChangePasswordForm, ForgotPasswordForm

from flexmeasures.auth.policy import user_can_reset_own_password


class FlexMeasuresForgotPasswordForm(ForgotPasswordForm):
    """Require a grant before sending password recovery instructions."""

    def validate(self, **kwargs) -> bool:
        if not super().validate(**kwargs):
            return False
        if not user_can_reset_own_password(self.user):
            self.email.errors.append("Password recovery is unavailable for this user.")
            return False
        return True


class FlexMeasuresChangePasswordForm(ChangePasswordForm):
    """Require the same grant for authenticated password changes."""

    def validate(self, **kwargs) -> bool:
        if not super().validate(**kwargs):
            return False
        if not user_can_reset_own_password(current_user):
            self.new_password.errors.append(
                "Password changes are unavailable for this user."
            )
            return False
        return True
