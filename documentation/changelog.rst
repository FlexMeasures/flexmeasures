
**********************
FlexMeasures Changelog
**********************



v1.0.0 | July XX, 2026
* In the UI, asset and sensor charts now render with Apache ECharts (canvas) by default, for much faster drawing and interaction on dense time series, while staying visually and functionally equivalent to the previous Vega-Lite charts, which remain available as a fallback via a toggle [see `PR #2234 <https://www.github.com/FlexMeasures/flexmeasures/pull/2234>`_]
* Breaking behaviour change: the top-level flex-context's ``relax-constraints`` field now defaults to ``True`` (matching the default already used within each ``commodities`` entry), so constraint violations are softly penalized by default instead of being hard constraints, unless explicitly set to ``False`` [see `PR #2172 <https://www.github.com/FlexMeasures/flexmeasures/pull/2172>`_]
* Support for creating new assets by using another asset as a template from the UI. [see `PR #2195 <https://www.github.com/FlexMeasures/flexmeasures/pull/2195>`_ and `PR #2268 <https://www.github.com/FlexMeasures/flexmeasures/pull/2268>`_
* In the UI, asset and sensor lists can be filtered by ID prefix through API-backed search fields [see `PR #2231 <https://www.github.com/FlexMeasures/flexmeasures/pull/2231>`_]
* Support configurable lower and upper bounds and snapping for forecast post-processing [see `PR #2273 <https://www.github.com/FlexMeasures/flexmeasures/pull/2273>`_]
* Floor off-clock API datetimes to a non-instantaneous sensor's resolution by default when ingesting sensor data, uploading sensor data, and handling scheduler flex-model timed events; configurable with the ``floor_datetimes_to_resolution`` sensor attribute [see `PR #2146 <https://www.github.com/FlexMeasures/flexmeasures/pull/2146>`_]
* Sensor references in flex-model and flex-context support various ways of filtering by source [see `PR #2209 <https://www.github.com/FlexMeasures/flexmeasures/pull/2209>`_]
* Let storage scheduling infer missing ``power-capacity`` from directional device capacities before falling back to site capacity, and default the missing opposite capacity to zero when only a non-zero ``consumption-capacity`` or ``production-capacity`` is configured [see `PR #2222 <https://www.github.com/FlexMeasures/flexmeasures/pull/2222>`_]
* Support multiple feeders to a shared storage [see `PR #2001 <https://www.github.com/FlexMeasures/flexmeasures/pull/2001>`_, `PR #2321 <https://www.github.com/FlexMeasures/flexmeasures/pull/2321>`_ and `PR #2322 <https://www.github.com/FlexMeasures/flexmeasures/pull/2322>`_]
* The flex-context can now define multiple commodities, each specifying their own prices and grid capacities [see `PR #1946 <https://www.github.com/FlexMeasures/flexmeasures/pull/1946>`_, `PR #2172 <https://www.github.com/FlexMeasures/flexmeasures/pull/2172>`_, `PR #2235 <https://www.github.com/FlexMeasures/flexmeasures/pull/2235>`_ and `PR #2271 <https://www.github.com/FlexMeasures/flexmeasures/pull/2271>`_]
* CLI support for adding/editing account attributes [see `PR #2242 <https://www.github.com/FlexMeasures/flexmeasures/pull/2242>`_]
* New storage flex-model field ``operation-modes`` confines a device's power to one of several power bands, following the S2 standard's operation modes — for example, a device that is either off or running at one fixed power [see `Issue #2113 <https://www.github.com/FlexMeasures/flexmeasures/issues/2113>`_]
* Improve chart axis domain for event values not around zero, with a per-sub-chart ``y-axis`` option in ``sensors_to_show`` (default ``zero``, which pads the axis out to include zero) that can be set to ``data`` to fit a sub-chart's y-axis to the values shown, to an explicit ``[min, max]`` domain that the axis will cover at least (expanding to fit data beyond it), or to a strict ``{"min": min, "max": max}`` domain that the axis will never exceed (clamping data beyond it, with a warning when that happens), editable from the graph editor [see `PR #2244 <https://www.github.com/FlexMeasures/flexmeasures/pull/2244>`_]
* Extended ``GET /api/v3_0/jobs/<uuid>`` with a ``result`` field containing ``unresolved`` and ``resolved`` soft state-of-charge constraint analysis (``soc-minima``/``soc-maxima`` violations or satisfied constraints, keyed by asset ID) for scheduling jobs; both arrays are empty when no SoC constraints were defined [see `PR #2072 <https://www.github.com/FlexMeasures/flexmeasures/pull/2072>`_]
* New ``soc-value-at-end`` flex-model field for storage devices: assigns a marginal value (fixed quantity or sensor reference) to energy left in storage at the end of the scheduling horizon, countering myopic depletion of the storage [see `PR #2310 <https://www.github.com/FlexMeasures/flexmeasures/pull/2310>`_]
* Extended the scheduling job ``result`` field with a ``num-beliefs`` field reporting the total number of beliefs (scheduled values) saved to the database [see `PR #2280 <https://www.github.com/FlexMeasures/flexmeasures/pull/2280>`_]
* Migrate the asset tree in the UI's Structure tab from Vega to ECharts, adding interactive pan/zoom navigation and refreshed node styling [see `PR #2025 <https://www.github.com/FlexMeasures/flexmeasures/pull/2025>`_]

Infrastructure / Support
----------------------
* Upgraded dependencies [see `PR #1485 <https://www.github.com/FlexMeasures/flexmeasures/pull/1485>`_, `PR #2215 <https://www.github.com/FlexMeasures/flexmeasures/pull/2215>`_ and `PR #2243 <https://www.github.com/FlexMeasures/flexmeasures/pull/2243>`_]
* Speed up post-processing of sensor data searches: latest-version filtering, deterministic-belief selection per event and chart-data serialization are now vectorized (up to three orders of magnitude faster on large search results) [see `PR #2328 <https://www.github.com/FlexMeasures/flexmeasures/pull/2328>`_]
* Prepare the ``device_scheduler`` to deal with commitments per device group [see `PR #1934 <https://www.github.com/FlexMeasures/flexmeasures/pull/1934>`_]
* Support storing encrypted connection secrets on organisations and assets, including utility functions, encryption key configuration, CLI commands to set and delete secrets, and UI tables that show stored secret names and optional expiration times without exposing their values [see `PR #2236 <https://www.github.com/FlexMeasures/flexmeasures/pull/2236>`_]
* Documentation section on the modelling choice for recording measurements, forecasts and schedules under one or multiple sensors [see `PR #2217 <https://www.github.com/FlexMeasures/flexmeasures/pull/2217>`_]
* Document source filters better, and make use of the source-types filter in the PV curtailment tutorial [see `PR #2261 <https://www.github.com/FlexMeasures/flexmeasures/pull/2261>`_]
* Document suggested cloud architecture [see `PR #2245 <https://www.github.com/FlexMeasures/flexmeasures/pull/2245>`_]
* Document the ``TRUSTED_HOSTS`` setting to safeguard against host poisoning from clients [see `PR #2246 <https://www.github.com/FlexMeasures/flexmeasures/pull/2246>`_]
* Document the various ways to inspect a (scheduling) job [see `PR #2247 <https://www.github.com/FlexMeasures/flexmeasures/pull/2247>`_]
* Automate Docker Hub image publishing and a PyPI install smoke test on release, add a manually-triggered QA workflow that runs the toy tutorials and HEMS walkthrough against a local Docker Compose stack, and add a helper script to list merged PRs since the last tag [see `PR #2260 <https://www.github.com/FlexMeasures/flexmeasures/pull/2260>`_]
* Make toy tutorials robust against pre-existing IDs [see `PR #2269 <https://www.github.com/FlexMeasures/flexmeasures/pull/2269>`_]
* Document multi-tenancy and consultancy tenant structures for hosts [see `PR #2176 <https://www.github.com/FlexMeasures/flexmeasures/pull/2176>`_]
* Warn hosts when the database schema is not at the latest migration, and skip startup template provisioning until migrations are applied [see `PR #2309 <https://www.github.com/FlexMeasures/flexmeasures/pull/2309>`_]
* Stop manual runs of the Docker publishing workflow from overwriting the ``latest`` image tag, and let them opt in to it explicitly [see `PR #2316 <https://www.github.com/FlexMeasures/flexmeasures/pull/2316>`_]
* Add a pre-commit hook that blocks image files (png, jpg, gif, bmp, tiff, webp, ico, psd) from being committed outside of ``flexmeasures/ui/static/`` and ``documentation/``, to protect the git history from binary bloat; screenshots belong in the ``FlexMeasures/screenshots`` repo instead [see `PR #2315 <https://www.github.com/FlexMeasures/flexmeasures/pull/2315>`_]
* Schedulers track devices via a typed device inventory, which classifies every flex-model entry once and serves as the single source of truth for device roles and canonical device indices [see `PR #2321 <https://www.github.com/FlexMeasures/flexmeasures/pull/2321>`_]

Bugfixes
-----------
* Fix column sorting on the assets page, including when combined with the search filter [see `PR #2314 <https://www.github.com/FlexMeasures/flexmeasures/pull/2314>`_]
* Fix forecasting with past or future regressors, which raised a ``TypeError`` on pandas 2.2 and higher [see `PR #2303 <https://www.github.com/FlexMeasures/flexmeasures/pull/2303>`_]
* Show why a CLI option was rejected (e.g. "No account found with id 9999") instead of only echoing the offending value [see `PR #2303 <https://www.github.com/FlexMeasures/flexmeasures/pull/2303>`_]
* Fix the task detail page returning a 500 for jobs whose meta data is not JSON-serializable [see `PR #2303 <https://www.github.com/FlexMeasures/flexmeasures/pull/2303>`_]
* Roll back before retrying the query behind ``[GET] /api/ops/getLatestTaskRun``, which otherwise reports an aborted transaction instead of the original database error [see `PR #2303 <https://www.github.com/FlexMeasures/flexmeasures/pull/2303>`_]
* Stamp a ``LatestTaskRun`` with the time it is recorded, rather than with the time the FlexMeasures process started [see `PR #2304 <https://www.github.com/FlexMeasures/flexmeasures/pull/2304>`_]
* Let storage scheduling treat missing constant SoC bounds as unconstrained lower or upper bounds [see `PR #2221 <https://www.github.com/FlexMeasures/flexmeasures/pull/2221>`_]
* Allow root assets belonging to different accounts to share the same name, while keeping asset names unique among root assets within the same account and among children of the same parent [see `PR #2226 <https://www.github.com/FlexMeasures/flexmeasures/pull/2226>`_]
* Fix queued train-predict forecasting jobs losing their resolved forecast window or failing on detached database objects in workers [see `PR #2035 <https://www.github.com/FlexMeasures/flexmeasures/pull/2035>`_]
* Fix multi-device storage scheduling misaligning devices with their assets when any flex-model entry is filtered out, which let a device inherit another device's power capacity and could silently drop a device (referencing its power sensor only through a nested ``consumption``/``production`` output reference) from the schedule [see `PR #2319 <https://www.github.com/FlexMeasures/flexmeasures/pull/2319>`_]


v0.33.1 | July 1, 2026
