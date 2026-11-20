"""Tests for flexmeasures/ui/static/js/replay-utils.js."""

BELIEF = """
    const MINUTE = 60000, HOUR = 60 * MINUTE, DAY = 24 * HOUR;
    const belief = (sensor, start, source, value, beliefTime) =>
        ({sensor: {id: sensor}, event_start: start, source: {id: source}, event_value: value, belief_time: beliefTime});
"""


def test_belief_timeline_keeps_the_most_recent_belief_per_event(assert_js):
    """The replay adds beliefs as belief time moves on, replacing older beliefs about the same event."""
    assert_js(
        """
        import { BeliefTimeline } from "/js/replay-utils.js";
        """
        + BELIEF
        + """
        // Deliberately not in belief-time order: the timeline sorts them.
        const timeline = new BeliefTimeline([
            belief(1, 0, 9, "newest", 30),
            belief(1, 0, 9, "old", 10),
            belief(1, 1, 9, "untouched", 10),
            belief(1, 0, 9, "same time, listed first", 40),
            belief(1, 0, 9, "newer", 20),
            belief(1, 0, 8, "other source", 20),
            belief(2, 0, 9, "other sensor", 20),
            belief(1, 0, 9, "same time, listed last", 40),
        ]);
        const values = () => Object.fromEntries(timeline.data.map(
            (b) => [`${b.sensor.id}_${b.event_start}_${b.source.id}`, b.event_value]));

        eq("nothing is known before the first belief", timeline.advanceTo(5), false);
        eq("so there is no data", timeline.data, []);
        eq("moving past beliefs reports a change", timeline.advanceTo(10), true);
        eq("beliefs known by then are shown", values(), {"1_0_9": "old", "1_1_9": "untouched"});
        eq("moving without passing beliefs reports no change", timeline.advanceTo(15), false);
        timeline.advanceTo(30);
        eq("the latest belief replaces the old one, per sensor, event and source", values(), {
            "1_0_9": "newest", "1_1_9": "untouched", "1_0_8": "other source", "2_0_9": "other sensor",
        });
        timeline.advanceTo(40);
        eq("of beliefs formed at the same time, the one listed last wins",
           values()["1_0_9"], "same time, listed last");
        eq("moving back in time reports a change", timeline.advanceTo(25), true);
        eq("and shows only what was known then, restoring the beliefs replaced since", values(), {
            "1_0_9": "newer", "1_1_9": "untouched", "1_0_8": "other source", "2_0_9": "other sensor",
        });
        eq("moving back without passing beliefs reports no change", timeline.advanceTo(21), false);
        timeline.advanceTo(10);
        eq("beliefs first known since are no longer shown", values(), {"1_0_9": "old", "1_1_9": "untouched"});
        eq("moving back to before the first belief reports a change", timeline.advanceTo(5), true);
        eq("and leaves no data", timeline.data, []);
        timeline.advanceTo(40);
        eq("moving forward again shows the same as before", values()["1_0_9"], "same time, listed last");
        """
    )


def test_infer_replay_step_follows_belief_timing(assert_js):
    """The step follows how often beliefs are formed, within each sensor and source, regardless of event timing."""
    assert_js(
        """
        import { inferReplayStep, DEFAULT_REPLAY_STEP_MS } from "/js/replay-utils.js";
        """
        + BELIEF
        + """
        // n updates, one per interval, each about the next 96 hourly events.
        const every = (interval, n, {sensor = 1, source = 1, offset = 0, jitter = 0} = {}) =>
            Array.from({length: n}, (_, i) => Array.from({length: 96}, (_, e) =>
                belief(sensor, e * HOUR, source, 0, offset + i * interval + (i % 2) * jitter))).flat();

        eq("hourly events updated every 15 minutes step by 15 minutes", inferReplayStep(every(15 * MINUTE, 8)), 15 * MINUTE);
        eq("a few seconds of jitter does not matter",
           inferReplayStep(every(15 * MINUTE, 8, {jitter: 7000})), 15 * MINUTE);
        eq("an interval that fits no whole number of times in an hour is rounded down",
           inferReplayStep(every(7 * MINUTE, 8)), 6 * MINUTE);
        eq("nor in a day", inferReplayStep(every(5 * HOUR, 8)), 4 * HOUR);
        eq("daily updates step by a day", inferReplayStep(every(DAY, 4)), DAY);
        eq("steps are at most a day", inferReplayStep(every(7 * DAY, 4)), DAY);
        eq("streams offset from each other are not read as more frequent updates",
           inferReplayStep([...every(HOUR, 6), ...every(HOUR, 6, {sensor: 2, offset: 2 * MINUTE}),
                            ...every(HOUR, 6, {source: 2, offset: 4 * MINUTE})]), HOUR);
        eq("the most common interval wins over occasional gaps",
           inferReplayStep([...every(15 * MINUTE, 8), ...every(15 * MINUTE, 3, {offset: 10 * HOUR})]), 15 * MINUTE);
        eq("data formed at a single belief time falls back to the default",
           inferReplayStep(every(HOUR, 1)), DEFAULT_REPLAY_STEP_MS);
        eq("no data falls back to the default", inferReplayStep([]), DEFAULT_REPLAY_STEP_MS);
        """
    )


def test_format_replay_step(assert_js):
    assert_js("""
        import { formatReplayStep } from "/js/replay-utils.js";
        eq("minutes", formatReplayStep(15 * 60000), "15 min");
        eq("hours", formatReplayStep(6 * 3600000), "6 h");
        eq("a day", formatReplayStep(86400000), "1 day");
        """)


def test_step_floor_counts_steps_from_the_start(assert_js):
    assert_js("""
        import { stepFloor } from "/js/replay-utils.js";
        eq("a time between boundaries floors to the previous one", stepFloor(1037, 1000, 15), 1030);
        eq("a boundary floors to itself", stepFloor(1030, 1000, 15), 1030);
        eq("the start is a boundary", stepFloor(1000, 1000, 15), 1000);
        """)


def test_step_before_counts_steps_from_the_start(assert_js):
    assert_js("""
        import { stepBefore } from "/js/replay-utils.js";
        eq("a time between boundaries steps back to the previous one", stepBefore(1037, 1000, 15), 1030);
        eq("a boundary steps back to the one before it", stepBefore(1030, 1000, 15), 1015);
        eq("the start steps back to before it, for the clock to stop at the start", stepBefore(1000, 1000, 15), 985);
        """)


def test_replay_data_follows_the_ruler(assert_js):
    """While playing, the data follows the step boundaries; while paused, it matches the ruler exactly, and it never goes back."""
    assert_js("""
        import { replayDataTime } from "/js/replay-utils.js";
        // A replay from 1000, in steps of 15
        eq("at the start, the start is shown", replayDataTime(1000, true, 1000, 15, null), 1000);
        eq("while playing, the last boundary passed is shown", replayDataTime(1037, true, 1000, 15, 1015), 1030);
        eq("while paused, the ruler's own time is shown", replayDataTime(1037, false, 1000, 15, 1030), 1037);
        eq("also before anything is shown", replayDataTime(1037, false, 1000, 15, null), 1037);
        eq("on resuming, what was shown at the pause stays", replayDataTime(1038, true, 1000, 15, 1037), 1037);
        eq("until the next boundary passes", replayDataTime(1045, true, 1000, 15, 1037), 1045);
        eq("switching to a longer step does not go back", replayDataTime(1050, true, 1000, 60, 1045), 1045);
        eq("a replay started over shows its start again", replayDataTime(1000, true, 1000, 15, 1045), 1000);
        """)


def test_replay_clock_runs_at_a_constant_rate(assert_js):
    """The clock's position follows the wall clock, however irregularly it is read."""
    assert_js("""
        import { ReplayClock } from "/js/replay-utils.js";
        const clock = new ReplayClock(1000, 100000, 10);
        eq("a new clock is paused at the start", [clock.playing, clock.position(0)], [false, 1000]);
        clock.play(50);
        eq("playing advances at the rate", clock.position(60), 1100);
        eq("however irregularly it is read", [clock.position(51), clock.position(150), clock.position(70)], [1010, 2000, 1200]);
        clock.pause(150);
        eq("pausing holds the position", clock.position(5000), 2000);
        eq("a paused clock stands still where it stopped", clock.motion, {position: 2000, wallTime: null, rate: 0, end: 2000});
        clock.play(6000);
        eq("resuming continues from there", clock.position(6010), 2100);
        clock.setRate(20, 6010);
        eq("changing the rate does not move the position", clock.position(6010), 2100);
        eq("and applies from then on", clock.position(6020), 2300);
        eq("a playing clock moves on at its rate from where that last changed, up to the end", clock.motion, {position: 2100, wallTime: 6010, rate: 20, end: 100000});
        clock.seek(5000, 6020);
        eq("seeking moves the position", clock.position(6020), 5000);
        eq("and keeps playing from there", clock.position(6030), 5200);
        eq("the position never passes the end", clock.position(1e9), 100000);
        clock.seek(0, 6030);
        eq("nor goes before the start", clock.position(6030), 1000);
        """)


def test_replay_clock_rewinds(assert_js):
    """The clock can also run backward, at the same rate, down to the start."""
    assert_js("""
        import { ReplayClock } from "/js/replay-utils.js";
        const clock = new ReplayClock(1000, 100000, 10);
        clock.seek(5000, 0);
        clock.play(0, -1);
        eq("rewinding plays the clock backward", [clock.playing, clock.rewinding, clock.position(10)], [true, true, 4900]);
        eq("its motion runs back at the rate, down to the start", clock.motion, {position: 5000, wallTime: 0, rate: -10, end: 1000});
        eq("the position never goes before the start", clock.position(1e9), 1000);
        clock.play(20, 1);
        eq("turning around keeps the position", [clock.position(20), clock.rewinding], [4800, false]);
        eq("and plays forward from there", clock.position(30), 4900);
        clock.play(40, -1);
        clock.pause(50, 5);
        eq("a rewinding clock pauses where it would be a little later, further back", clock.position(50), 4850);
        eq("gliding back to there", [clock.motion, clock.gliding(54), clock.gliding(55)],
           [{position: 5000, wallTime: 40, rate: -10, end: 4850}, true, false]);
        """)


def test_replay_clock_glides_to_a_stop(assert_js):
    """A pause can land a little ahead, so that what moves along with the clock by itself stops there instead of jumping back."""
    assert_js("""
        import { ReplayClock } from "/js/replay-utils.js";
        const clock = new ReplayClock(1000, 100000, 10);
        clock.play(0);
        clock.pause(100, 5);
        eq("the clock pauses where it would be a little later", clock.position(100), 2050);
        eq("its motion runs on as it was, up to there", clock.motion, {position: 1000, wallTime: 0, rate: 10, end: 2050});
        eq("it is gliding until it gets there", [clock.gliding(100), clock.gliding(104.9)], [true, true]);
        eq("and no longer after", [clock.gliding(105), clock.gliding(200)], [false, false]);
        clock.setRate(20, 102);
        eq("a new rate does not change a glide", clock.motion, {position: 1000, wallTime: 0, rate: 10, end: 2050});
        clock.seek(3000, 103);
        eq("seeking stops it", [clock.motion, clock.gliding(103)], [{position: 3000, wallTime: null, rate: 0, end: 3000}, false]);
        clock.play(200);
        clock.pause(210, 5);
        clock.play(212);
        eq("so does resuming", clock.motion, {position: 3300, wallTime: 212, rate: 20, end: 100000});
        clock.pause(220);
        eq("a pause without a glide stops right there", [clock.position(220), clock.gliding(220)], [3460, false]);
        clock.pause(230, 5);
        eq("pausing a paused clock leaves it where it is", clock.position(230), 3460);
        """)


def test_redraw_durations_tell_the_shortest_recent_one(assert_js):
    assert_js("""
        import { RedrawDurations } from "/js/replay-utils.js";
        const durations = new RedrawDurations(3);
        eq("nothing is expected before the first redraw", durations.shortest, 0);
        [60, 80, 90].forEach((ms) => durations.add(ms));
        eq("the shortest recent duration is expected", durations.shortest, 60);
        durations.add(100);
        eq("older durations are forgotten", durations.shortest, 80);
        """)
