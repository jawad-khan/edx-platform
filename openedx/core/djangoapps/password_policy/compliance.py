"""
Utilities for enforcing and tracking compliance with password policy rules.
"""
from datetime import datetime

import pytz
from django.conf import settings
from django.utils.translation import ugettext as _

from util.date_utils import DEFAULT_SHORT_DATE_FORMAT, strftime_localized
from util.password_policy_validators import validate_password


class NonCompliantPasswordException(Exception):
    """
    Exception that should be raised when a user who is required to be compliant with password policy requirements
    is found to have a non-compliant password.
    """
    pass


class NonCompliantPasswordWarning(Exception):
    """
    Exception that should be raised when a user who will soon be required to be compliant with password policy
    requirements is found to have a non-compliant password.
    """
    pass


def should_enforce_compliance_on_login():
    """
    Returns a boolean indicating whether or not password policy compliance should be enforced on login.
    """
    config = _rollout_config()
    return config.get('ENFORCE_COMPLIANCE_ON_LOGIN', False)


def _capitalize_first(s):
    """
    Capitalize only the first letter and leave the rest alone. Note that normal Python capitalize() will
    lowercase all other letters. This does not.
    """
    return s[0].upper() + s[1:]


def enforce_compliance_on_login(user, password):
    """
    Verify that the user's password is compliant with password policy rules and determine what should be done
    if it is not.

    Raises NonCompliantPasswordException when the password is found to be non-compliant and the compliance deadline
    for the user has been reached. In this case, login should be prevented.

    Raises NonCompliantPasswordWarning when the password is found to be non-compliant and the compliance deadline for
    the user is in the future.

    Returns None when the password is found to be compliant, or when no deadline for compliance has been set for the
    user.

    Important: This method should only be called AFTER the user has been authenticated.
    """
    is_compliant = _check_user_compliance(user, password)
    if is_compliant:
        return

    deadline = _get_compliance_deadline_for_user(user)
    if deadline is None:
        return

    now = datetime.now(pytz.UTC)
    if now >= deadline:
        raise NonCompliantPasswordException(
            _capitalize_first(_(
                '{platform_name} now requires more complex passwords. Your current password does not meet the new '
                'requirements. Change your password now using the "Forgot password?" link below to continue using the '
                'site. Thank you for helping us keep your data safe.'
            ).format(
                platform_name=settings.PLATFORM_NAME
            ))
        )
    else:
        raise NonCompliantPasswordWarning(
            _capitalize_first(_(
                '{platform_name} now requires more complex passwords. Your current password does not meet the new '
                'requirements. You must change your password by {deadline} to be able to continue using the site. '
                'A password reset e-mail has been sent to the address associated with this account.'
            ).format(
                platform_name=settings.PLATFORM_NAME,
                deadline=strftime_localized(deadline, DEFAULT_SHORT_DATE_FORMAT)
            ))
        )


def _rollout_config():
    """
    Return a dictionary with configuration settings for managing the rollout of password policy compliance
    enforcement.
    """
    return getattr(settings, 'PASSWORD_POLICY_COMPLIANCE_ROLLOUT_CONFIG', {})


def _check_user_compliance(user, password):
    """
    Returns a boolean indicating whether or not the user is compliant with password policy rules.
    """
    try:
        validate_password(password, user=user, password_reset=False)
        return True
    except Exception:  # pylint: disable=broad-except
        # If anything goes wrong, we should assume the password is not compliant but we don't necessarily
        # need to prevent login.
        return False


def _get_compliance_deadline_for_user(user):
    """
    Returns the date that the user will be required to comply with password policy rules, or None if no such date
    applies to this user. If a deadline is not set, it will fall back to a more general deadline that is set.
    """
    config = _rollout_config()

    # Implied hierarchy of general->staff in terms of scope, so we'll use each as a fallback to the other for any
    # blank fields.
    general_deadline = config.get('GENERAL_USER_COMPLIANCE_DEADLINE')
    privilege_deadline = config.get('ELEVATED_PRIVILEGE_USER_COMPLIANCE_DEADLINE', general_deadline)
    staff_deadline = config.get('STAFF_USER_COMPLIANCE_DEADLINE', privilege_deadline)

    # Now only keep the deadlines that apply to this user
    privilege_deadline = privilege_deadline if privilege_deadline and _user_has_course_access_role(user) else None
    staff_deadline = staff_deadline if staff_deadline and user.is_staff else None

    # Take minimum remaining deadline
    filtered_deadlines = filter(None, (staff_deadline, privilege_deadline, general_deadline,))
    return min(filtered_deadlines) if filtered_deadlines else None


def _user_has_course_access_role(user):
    """
    Returns a boolean indicating whether or not the user is known to have at least one course access role.
    """
    try:
        return user.courseaccessrole_set.exists()
    except Exception:  # pylint: disable=broad-except
        return False
