from sqlalchemy import func, select

from flexmeasures.data.models.user import Account


def test_fresh_db_writes_rows(fresh_db):
    """Leave rows behind, which the next test must not see."""
    account = Account(name="left behind")
    fresh_db.session.add(account)
    fresh_db.session.commit()

    # Check that the rows were written, so that the next test cannot pass for lack of rows.
    assert account.id == 1
    assert fresh_db.session.scalar(select(func.count()).select_from(Account)) == 1


def test_fresh_db_is_empty_and_ids_restart(fresh_db):
    """The next test starts with empty tables and restarted sequences."""
    assert (
        fresh_db.session.scalar(select(func.count()).select_from(Account)) == 0
    ), "rows leaked from the previous test"

    account = Account(name="new")
    fresh_db.session.add(account)
    fresh_db.session.commit()
    assert account.id == 1, "sequence was not restarted"
