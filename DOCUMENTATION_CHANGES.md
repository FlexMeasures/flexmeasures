# Documentation Updates for --resolution Parameter (PR #1857)

## Summary

This documentation update adds comprehensive guidance for the new `--resolution` parameter in the `flexmeasures add schedule` CLI command and corresponding API endpoint. The parameter allows users to control the granularity of scheduling decisions, trading off precision for computational speed.

## Changes Made

### 1. Main Tutorial Documentation (`documentation/tut/forecasting_scheduling.rst`)

Added a new dedicated section **"Scheduling resolution"** (`_scheduling_resolution` anchor) that explains:

- **When to use custom resolution**: Three key scenarios
  - Reduce computational complexity for long planning horizons
  - Match control system limitations that can only adjust at specific intervals
  - Trade precision for speed when exact timing is less critical

- **How it works**: Clear explanation that scheduling happens at the requested resolution but results are saved at the sensor's native `event_resolution`

- **Example usage**: Complete CLI example showing how to use `--resolution PT2H`

- **Important limitations**: Two key warnings
  1. Resolution must be a multiple of sensor's `event_resolution` (e.g., PT15M → PT30M, PT1H, PT2H work; PT20M doesn't)
  2. Data sources (prices, inflexible devices) must have compatible resolutions - equal to or finer than scheduling resolution, or exact divisors

- **Default behavior**: Explains what happens when `--resolution` is omitted
  - Sensor scheduling: uses sensor's `event_resolution`
  - Asset scheduling: infers from device sensors

### 2. API Documentation Addition

Added a note in the API scheduling section showing how to use `resolution` in API requests:

```json
{
    "start": "2015-06-02T10:00:00+00:00",
    "resolution": "PT1H",
    "flex-model": {
        "sensor": 15,
        "soc-at-start": "12.1 kWh"
    }
}
```

With a reference to the detailed `scheduling_resolution` section.

### 3. Toy Example Tutorial Update (`documentation/tut/toy-example-from-scratch.rst`)

Enhanced the note about `flexmeasures add schedule` command options to include:
- Reference to custom scheduling resolution via `--resolution`
- Link to the new `scheduling_resolution` section
- Better organization of available options

### 4. Tutorial Script Demonstration (`documentation/tut/scripts/run-tutorial2-in-docker.sh`)

Added a practical demonstration at the end of Tutorial 2:
- Compares default 15-minute resolution scheduling with hourly resolution (`--resolution PT1H`)
- Includes explanatory echo statements to guide users
- Shows that the schedule still has 15-minute data points, but values only change each hour
- Uses the same battery, solar, and price data from earlier in the tutorial

This provides users with a working example they can run to see the feature in action.

## Why These Changes Matter

### For Users

1. **Clear guidance**: Users understand when and why to use custom resolution
2. **Avoid pitfalls**: Warnings explain common failure scenarios (incompatible resolutions)
3. **Practical example**: Tutorial script demonstrates the feature with real commands
4. **Cross-referenced**: Users can find information from multiple entry points

### For Developer Experience

1. **Discoverable**: Feature is documented where users look for scheduling information
2. **Complete**: Covers CLI, API, limitations, and defaults
3. **Actionable**: Includes working examples that users can copy and run
4. **Linked**: Uses RST cross-references so users can navigate between related topics

## Technical Details

### Sensor Resolutions in Toy Account
- Battery/solar sensors: PT15M (15 minutes)
- Day-ahead price sensor: PT1H (1 hour)

This means:
- ✅ Scheduling at PT1H works (PT1H is multiple of PT15M, and prices are at PT1H)
- ✅ Scheduling at PT30M works (PT30M is multiple of PT15M, and PT1H can aggregate to PT30M)
- ❌ Scheduling at PT2H fails if using hourly prices directly without proper aggregation

### Tutorial Script Choice

Tutorial 2 was chosen for the demonstration because:
1. It uses day-ahead prices at PT1H resolution (loaded in Tutorial 1)
2. Scheduling at PT1H resolution is a natural fit with hourly price data
3. It's a simple scenario that clearly shows the resolution effect
4. The tutorial is already about scheduling, so it's contextually appropriate

## Files Modified

1. `documentation/tut/forecasting_scheduling.rst` - Main documentation (new section added)
2. `documentation/tut/toy-example-from-scratch.rst` - Enhanced note about CLI options
3. `documentation/tut/scripts/run-tutorial2-in-docker.sh` - Added practical demonstration

## Testing Recommendations

1. Build the documentation and verify RST rendering is correct
2. Run Tutorial 2 script to verify the new commands execute successfully
3. Check that cross-references link correctly (`:ref:`scheduling_resolution``)
4. Verify the tutorial produces expected output (schedule with hourly changes)

## Future Improvements (Not in Scope)

These could be considered for future documentation updates:
1. Add visualization showing difference between PT15M and PT1H schedules
2. Include performance benchmarks for different resolutions
3. Add troubleshooting section for common resolution-related errors
4. Document the exact aggregation logic for data sources at different resolutions
