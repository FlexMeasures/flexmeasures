"""The CLI may put an asset under a parent of another organisation, but says so.

(On 1.1, these tests live in test_data_add_db.py and test_data_edit.py, which can undo their new rows.)
"""

import pytest
from sqlalchemy import select

from flexmeasures.cli.tests.utils import check_command_ran_without_error, to_flags
from flexmeasures.data.models.generic_assets import GenericAsset


def _flat(output: str) -> str:
    """The CLI output with line breaks (from wrapping) turned into spaces."""
    return " ".join(output.split())


@pytest.mark.parametrize(
    "child_account, parent_account, warning",
    [
        (
            "Supplier",
            "Prosumer",
            "Warning: asset 'CLI child' (id {child}) of organisation 'Test Supplier Account' (id {child_account})"
            " gets parent 'CLI parent' (id {parent}) from another organisation, 'Test Prosumer Account' (id {parent_account}).",
        ),
        (
            None,
            "Prosumer",
            "Warning: public asset 'CLI child' (id {child}) gets parent 'CLI parent' (id {parent})"
            " from organisation 'Test Prosumer Account' (id {parent_account}).",
        ),
        ("Prosumer", "Prosumer", None),
    ],
    ids=["foreign-parent", "public-child-private-parent", "same-account-parent"],
)
def test_add_asset_warns_about_a_parent_in_another_organisation(
    app,
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    run_as_cli,
    child_account,
    parent_account,
    warning,
):
    from flexmeasures.cli.data_add import add_asset

    accounts = setup_accounts_fresh_db
    asset_type = setup_generic_asset_types_fresh_db["battery"]
    fresh_db.session.flush()
    parent = GenericAsset(
        name="CLI parent",
        generic_asset_type_id=asset_type.id,
        account_id=accounts[parent_account].id,
    )
    fresh_db.session.add(parent)
    fresh_db.session.commit()

    cli_input = {
        "name": "CLI child",
        "asset-type": asset_type.id,
        "parent-asset": parent.id,
    }
    if child_account is not None:
        cli_input["account"] = accounts[child_account].id
    runner = app.test_cli_runner()
    result = runner.invoke(add_asset, to_flags(cli_input))
    check_command_ran_without_error(result)

    child = fresh_db.session.execute(
        select(GenericAsset).filter_by(name="CLI child", parent_asset_id=parent.id)
    ).scalar_one()  # the asset is created anyway
    if warning is None:
        assert "Warning:" not in result.output
    else:
        expected = warning.format(
            child=child.id,
            child_account=child.account_id,
            parent=parent.id,
            parent_account=parent.account_id,
        )
        assert expected in _flat(result.output)


@pytest.mark.parametrize(
    "child_account, parent_account, warns",
    [
        ("Supplier", "Prosumer", True),
        (None, "Prosumer", True),
        ("Prosumer", "Prosumer", False),
    ],
)
def test_transfer_parenthood_warns_about_a_parent_in_another_organisation(
    app,
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    child_account,
    parent_account,
    warns,
):
    """Moving an asset under a parent of another organisation works from the CLI, with a warning."""
    from flexmeasures.cli.data_edit import transfer_parenthood

    accounts = setup_accounts_fresh_db
    asset_type = setup_generic_asset_types_fresh_db["battery"]
    fresh_db.session.flush()
    parent = GenericAsset(
        name="new parent",
        generic_asset_type_id=asset_type.id,
        account_id=accounts[parent_account].id,
    )
    child = GenericAsset(
        name="moving child",
        generic_asset_type_id=asset_type.id,
        account_id=accounts[child_account].id if child_account else None,
    )
    fresh_db.session.add_all([parent, child])
    fresh_db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(
        transfer_parenthood,
        to_flags({"asset": child.id, "new_parent": parent.id}),
        input="y\n",  # the existing confirmation of a move between accounts
    )
    check_command_ran_without_error(result)
    assert child.parent_asset_id == parent.id
    warning = (
        f"gets parent 'new parent' (id {parent.id})"
        f" from {'another organisation, ' if child_account else 'organisation '}'Test Prosumer Account'"
    )
    assert (warning in _flat(result.output)) is warns
    assert ("Warning:" in result.output) is warns


@pytest.mark.parametrize(
    "parent_account, new_owner, warns",
    [("Prosumer", "Supplier", True), ("Prosumer", "Prosumer", False)],
)
def test_transfer_ownership_warns_about_a_parent_left_in_another_organisation(
    app,
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    parent_account,
    new_owner,
    warns,
):
    """Transferring an asset (and its children) away from its parent's organisation warns about the parent left behind."""
    from flexmeasures.cli.data_edit import transfer_ownership

    accounts = setup_accounts_fresh_db
    asset_type = setup_generic_asset_types_fresh_db["battery"]
    fresh_db.session.flush()
    parent = GenericAsset(
        name="staying parent",
        generic_asset_type_id=asset_type.id,
        account_id=accounts[parent_account].id,
    )
    fresh_db.session.add(parent)
    fresh_db.session.flush()
    child = GenericAsset(
        name="moving child",
        generic_asset_type_id=asset_type.id,
        account_id=accounts["Dummy"].id,
        parent_asset_id=parent.id,
    )
    fresh_db.session.add(child)
    fresh_db.session.flush()
    grandchild = GenericAsset(
        name="moving grandchild",
        generic_asset_type_id=asset_type.id,
        account_id=accounts["Dummy"].id,
        parent_asset_id=child.id,
    )
    fresh_db.session.add(grandchild)
    fresh_db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(
        transfer_ownership,
        to_flags({"asset": child.id, "new_owner": accounts[new_owner].id}),
    )
    check_command_ran_without_error(result)
    assert child.account_id == grandchild.account_id == accounts[new_owner].id
    warning = (
        f"Warning: asset 'moving child' (id {child.id}) of organisation 'Test Supplier Account'"
        f" (id {accounts['Supplier'].id}) gets parent 'staying parent' (id {parent.id})"
        f" from another organisation, 'Test Prosumer Account' (id {accounts['Prosumer'].id})."
    )
    assert (warning in _flat(result.output)) is warns
    # only the asset itself gets a warning, not the grandchild, whose parent moves along
    assert result.output.count("Warning:") == (1 if warns else 0)
