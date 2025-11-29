from __future__ import annotations

from sqlalchemy import select, Select, or_, and_

from flexmeasures.data.models.user import User as UserModel, Account


def query_users_by_search_terms(
    search_terms: list[str] | None,
    filter_statement: bool = True,
) -> Select:
    select_statement = select(UserModel)
    if search_terms is not None:
        filter_statement = filter_statement & and_(
            *(
                or_(
                    UserModel.email.ilike(f"%{term}%"),
                    UserModel.username.ilike(f"%{term}%"),
                    UserModel.account.has(Account.name.ilike(f"%{term}%")),
                )
                for term in search_terms
            )
        )

    query = select_statement.where(filter_statement)
    return query
