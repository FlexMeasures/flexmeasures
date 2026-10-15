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

A few files, such as `flexmeasures.js` and `map-init.js`, are classic scripts rather than modules:
their functions become globals, and they expect libraries such as jQuery or Leaflet on the page.
Their tests put stand-ins for those libraries on `window`, then load the script with a `<script>` element
(see `test_flexmeasures_js.py`).

Logic that lives inline in a template cannot be reached this way.
To test it, move it into a module under `flexmeasures/ui/static/js` and import that from the template,
as `asset-tree.js` and `flex-context-utils.js` were moved out of `_macros.html` and `assets/asset_context.html`.

Run them with the rest of the suite, or on their own:

```bash
pytest flexmeasures/ui/tests/js
```

The tests are skipped when `selenium` is missing or no Chrome is available, so a checkout without
either still runs the Python suite. Note that some behaviour is timezone-dependent; the suite is
written to pass under any `TZ`, and is exercised under several.
