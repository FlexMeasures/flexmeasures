"""
Account-admins may only give the consultant role to users in an account with the Consultancy account role.
"""

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.auth.policy import ACCOUNT_ADMIN_ROLE, CONSULTANT_ROLE
from flexmeasures.data.models.user import Role
from flexmeasures.data.services.users import find_user_by_email


def _role(db, name: str) -> Role:
    return db.session.execute(select(Role).filter_by(name=name)).scalar_one()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_account_admin_cannot_give_the_consultant_role_outside_a_consultancy(
    fresh_db, client, setup_roles_users_fresh_db, requesting_user
):
    """The Prosumer account has no Consultancy role, so its account-admin cannot make a consultant."""
    member = find_user_by_email("test_prosumer_user@seita.nl")
    consultant_role = _role(fresh_db, CONSULTANT_ROLE)

    response = client.patch(
        url_for("UserAPI:patch", id=member.id),
        json={"flexmeasures_roles": [consultant_role.id]},
    )

    assert response.status_code == 403, response.json
    fresh_db.session.expire_all()
    assert (
        consultant_role
        not in find_user_by_email("test_prosumer_user@seita.nl").flexmeasures_roles
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_account_admin_can_still_take_the_consultant_role_away(
    fresh_db, client, setup_roles_users_fresh_db, requesting_user
):
    member = find_user_by_email("test_prosumer_user@seita.nl")
    member.flexmeasures_roles.append(_role(fresh_db, CONSULTANT_ROLE))
    fresh_db.session.commit()

    response = client.patch(
        url_for("UserAPI:patch", id=member.id), json={"flexmeasures_roles": []}
    )

    assert response.status_code == 200, response.json
    assert response.json["flexmeasures_roles"] == []


@pytest.mark.parametrize("requesting_user", ["test_consultant@seita.nl"], indirect=True)
def test_account_admin_of_a_consultancy_can_give_the_consultant_role(
    fresh_db, client, setup_roles_users_fresh_db, requesting_user
):
    requesting_user.flexmeasures_roles.append(_role(fresh_db, ACCOUNT_ADMIN_ROLE))
    fresh_db.session.commit()
    colleague = find_user_by_email(
        "test_consultancy_user_without_consultant_access@seita.nl"
    )
    consultant_role = _role(fresh_db, CONSULTANT_ROLE)

    response = client.patch(
        url_for("UserAPI:patch", id=colleague.id),
        json={"flexmeasures_roles": [consultant_role.id]},
    )

    assert response.status_code == 200, response.json
    assert response.json["flexmeasures_roles"] == [consultant_role.id]
