def test_add_annotation(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_annotation

    runner = app.test_cli_runner()
    result = runner.invoke(
        add_annotation,
        [
            *("--content", "Company founding day"),
            *("--at", "2016-05-11T00:00+02:00"),
            *("--account-id", "1"),
            *("--user-id", "1"),
        ],
    )
    # Check result for success
    assert "Successfully added annotation" in result.output
    # todo: Check database


def test_add_holidays(app, db, setup_roles_users):
    from flexmeasures.cli.data_add import add_holidays

    runner = app.test_cli_runner()
    result = runner.invoke(
        add_holidays,
        [
            *("--year", "2020"),
            *("--country", "NL"),
            *("--account-id", "1"),
        ],
    )
    # Check result for 11 public holidays
    assert "'NL': 11" in result.output
    # todo: Check database
