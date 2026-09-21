"""Tests for flexmeasures/ui/static/js/replay-utils.js."""


def test_partition(assert_js):
    assert_js("""
        import { partition } from "/js/replay-utils.js";
        eq("elements passing the test go left, the others right",
           partition([1, 2, 3, 4, 5], (x) => x % 2 === 0), [[2, 4], [1, 3, 5]]);
        eq("the decision function also gets the index",
           partition(["a", "b", "c"], (x, i) => i < 1), [["a"], ["b", "c"]]);
        eq("an empty array gives two empty arrays", partition([], () => true), [[], []]);
        """)


def test_update_beliefs_keeps_the_most_recent_belief_per_event(assert_js):
    """The replay adds beliefs as time moves on, replacing older beliefs about the same event."""
    assert_js("""
        import { updateBeliefs } from "/js/replay-utils.js";
        const belief = (sensor, start, source, value) =>
            ({sensor: {id: sensor}, event_start: start, source: {id: source}, event_value: value});
        const old = [belief(1, 0, 9, "old"), belief(1, 1, 9, "untouched")];
        const updated = updateBeliefs(old, [
            belief(1, 0, 9, "newer"),
            belief(1, 0, 9, "newest"),
            belief(1, 0, 8, "other source"),
            belief(2, 0, 9, "other sensor"),
        ]);
        const byKey = Object.fromEntries(updated.map((b) => [`${b.sensor.id}_${b.event_start}_${b.source.id}`, b.event_value]));
        eq("the latest of the new beliefs replaces the old one", byKey["1_0_9"], "newest");
        eq("events without new beliefs keep their old one", byKey["1_1_9"], "untouched");
        eq("beliefs by another source are kept apart", byKey["1_0_8"], "other source");
        eq("beliefs about another sensor are kept apart", byKey["2_0_9"], "other sensor");
        eq("one belief per sensor, event and source", updated.length, 4);
        """)


def test_abortable_timeout(assert_js):
    assert_js("""
        import { setAbortableTimeout } from "/js/replay-utils.js";
        const fired = [];
        const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

        setAbortableTimeout(() => fired.push("plain"), 5);
        const aborted = new AbortController();
        setAbortableTimeout(() => fired.push("aborted"), 5, aborted.signal);
        aborted.abort();
        const kept = new AbortController();
        setAbortableTimeout(() => fired.push("kept"), 5, kept.signal);
        await wait(40);
        kept.abort();  // too late to matter

        eq("timers fire unless aborted first", fired.sort(), ["kept", "plain"]);
        """)
