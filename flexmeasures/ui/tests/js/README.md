# JavaScript tests

The modules under `flexmeasures/ui/static/js` are plain ES modules, so they can be exercised
directly, without a running FlexMeasures instance and without a Node.js toolchain.

`conftest.py` serves the modules over HTTP, because ES module imports do not work over `file://`,
and runs a page of assertions in headless Chrome. Each test passes a snippet of JavaScript that
imports what it needs and calls `check(label, passed, detail)` or `eq(label, actual, expected)`;
pytest reports whatever did not pass.

```python
def test_something(assert_js):
    assert_js(
        """
        import { missingRanges } from "/js/chart-data-cache.js";
        eq("an unchanged window needs no fetch", missingRanges(a, b, loaded).length, 0);
        """
    )
```

Run them with the rest of the suite, or on their own:

```bash
pytest flexmeasures/ui/tests/js
```

The tests are skipped when `selenium` is missing or no Chrome is available, so a checkout without
either still runs the Python suite. Note that some behaviour is timezone-dependent; the suite is
written to pass under any `TZ`, and is exercised under several.
