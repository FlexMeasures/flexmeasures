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
        eq("moving back in time reports a change", timeline.advanceTo(10), true);
        eq("and shows only what was known then", values(), {"1_0_9": "old", "1_1_9": "untouched"});
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
        eq("a paused clock is anchored where it stopped, without moving on", clock.anchor, {position: 2000, wallTime: null, rate: 0});
        clock.play(6000);
        eq("resuming continues from there", clock.position(6010), 2100);
        clock.setRate(20, 6010);
        eq("changing the rate does not move the position", clock.position(6010), 2100);
        eq("and applies from then on", clock.position(6020), 2300);
        eq("a playing clock is anchored where its rate last changed, moving on at that rate", clock.anchor, {position: 2100, wallTime: 6010, rate: 20});
        clock.seek(5000, 6020);
        eq("seeking moves the position", clock.position(6020), 5000);
        eq("and keeps playing from there", clock.position(6030), 5200);
        eq("the position never passes the end", clock.position(1e9), 100000);
        clock.seek(0, 6030);
        eq("nor goes before the start", clock.position(6030), 1000);
        """)
