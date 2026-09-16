"""Does the old harness hand one run the previous run's results?"""
def test_two_runs_do_not_share_results(js_runner):
    first = js_runner('check("first run", true, "");')
    second = js_runner('check("second run", true, "");')
    assert [c["label"] for c in first] == ["first run"], first
    assert [c["label"] for c in second] == ["second run"], second
