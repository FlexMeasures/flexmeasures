from flexmeasures.cli.tests.utils import check_command_ran_without_error


def test_list_plans(app, fresh_db):
    from flexmeasures.cli.data_show import list_plans
    from flexmeasures.data.models.user import Plan, RateLimitKey

    db = fresh_db
    db.session.add(
        Plan(
            name="Pro",
            trigger_rate_limit="60 per 5 minutes",
            rate_limit_key=RateLimitKey.ACCOUNT,
            max_assets=200,
            legacy=True,
        )
    )
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(list_plans)

    check_command_ran_without_error(result)
    assert "All plans on this" in result.output
    for expected in ("Pro", "60 per 5 minutes", "account"):
        assert expected in result.output
    # Quotas are not enforced yet, so we do not list them
    for not_expected in ("Max assets", "200"):
        assert not_expected not in result.output


def test_list_plans_without_any_plan(app, fresh_db):
    from flexmeasures.cli.data_show import list_plans

    runner = app.test_cli_runner()
    result = runner.invoke(list_plans)

    assert result.exit_code != 0
    assert "No plans created yet" in result.output


def test_show_accounts(app, fresh_db, setup_accounts_fresh_db):
    from flexmeasures.cli.data_show import show_account

    fresh_db.session.flush()  # get IDs in DB

    runner = app.test_cli_runner()
    result = runner.invoke(
        show_account, ["--id", setup_accounts_fresh_db["Prosumer"].id]
    )

    assert "Account Test Prosumer Account" in result.output
    assert "No users in account" in result.output
    check_command_ran_without_error(result)
