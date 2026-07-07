---
applyTo: "**/*.py"
---
# Timezone-Aware Datetimes

FlexMeasures treats naive datetimes as an error. All datetime objects must be timezone-aware.

## Creating datetimes

```python
# ✅ Correct: always timezone-aware
from datetime import datetime, timezone
dt = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

# ❌ Wrong: naive datetime
dt = datetime(2024, 1, 15, 10, 0, 0)
```

## Pandas DatetimeIndex

```python
# ✅ Correct: localize naive index
index = index.tz_localize("Europe/Amsterdam")

# ✅ Correct: convert aware index to different timezone
index = index.tz_convert("Europe/Amsterdam")

# ❌ Wrong: arithmetic on timezone-naive index near DST transitions
```

## Timezone configuration

| Setting | Purpose |
|---------|---------|
| `FLEXMEASURES_TIMEZONE` | Platform-wide default (default: `"Asia/Seoul"`) |
| `current_user.timezone` | User-specific timezone |
| `sensor.timezone` | Sensor-specific timezone for event timestamps |

## Nominal durations (ISO 8601)

Nominal durations like `P1M` (one month) cannot be converted to a `timedelta` without a reference datetime. Always pass a start datetime when grounding nominal durations:

```python
# ❌ Wrong: P1M has no fixed length
delta = isodate.parse_duration("P1M")  # returns isodate.Duration, not timedelta

# ✅ Correct: ground nominal duration to a calendar date
start = datetime(2024, 1, 1, tzinfo=timezone.utc)
end = start + isodate.parse_duration("P1M")  # Jan 1 + 1 month = Feb 1
```

## DST transitions

- Spring forward / fall back transitions cause off-by-one-hour bugs.
- When iterating over hourly slots, use `pd.date_range` with `freq` rather than adding `timedelta(hours=1)` in a loop.
- Test DST boundary cases explicitly (e.g., `Europe/Amsterdam` on last Sunday of March and October).

## Documentation examples

All code examples in documentation must use timezone-aware datetimes:

```python
# ✅ In docs
from datetime import datetime, timezone
start_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
```

Never show a naive `datetime(...)` call in user-facing documentation or in log statements.
