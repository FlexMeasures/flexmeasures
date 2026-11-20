// Replay utils
//
// A replay moves a belief time forward through the shown date range,
// drawing the data as it was known at that belief time.
// Only belief timing matters here: event times play no role in how the replay advances.

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// Step sizes that fit a whole number of times in an hour or in a day.
export const REPLAY_STEPS_MS = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 480, 720, 1440].map((m) => m * MINUTE);

// The step used when the data says nothing about how often beliefs are formed.
export const DEFAULT_REPLAY_STEP_MS = HOUR;

// Belief time passing per ms of playback at speed 1×: 10 hours per second.
export const BASE_REPLAY_RATE = (10 * HOUR) / 1000;

function streamKey(belief) {
  return belief.sensor.id + "_" + belief.source.id;
}

function beliefKey(belief) {
  return belief.sensor.id + "_" + belief.event_start + "_" + belief.source.id;
}

/**
 * Infers a replay step from how often beliefs are formed.
 *
 * Intervals are taken between consecutive belief times within each stream of data (one sensor, one source),
 * because interleaving streams would make updates look more frequent than any single stream is.
 * The most common interval, in whole minutes, is rounded down to the largest step in REPLAY_STEPS_MS,
 * so each regular update gets a step of its own.
 * Belief times less than half a minute apart count as the same update.
 *
 * @param {Array} beliefs Beliefs, with belief_time in ms.
 * @return {number}       Step in ms.
 */
export function inferReplayStep(beliefs) {
  const timesByStream = new Map();
  for (const belief of beliefs) {
    const key = streamKey(belief);
    if (!timesByStream.has(key)) timesByStream.set(key, new Set());
    timesByStream.get(key).add(belief.belief_time);
  }
  const countByMinutes = new Map();
  for (const times of timesByStream.values()) {
    const sorted = [...times].sort((a, b) => a - b);
    for (let i = 1; i < sorted.length; i++) {
      const minutes = Math.round((sorted[i] - sorted[i - 1]) / MINUTE);
      if (minutes > 0) countByMinutes.set(minutes, (countByMinutes.get(minutes) || 0) + 1);
    }
  }
  let mode = null;
  for (const [minutes, count] of countByMinutes) {
    // On a tie, the shorter interval wins, so no stream's updates get merged.
    if (mode === null || count > countByMinutes.get(mode) || (count === countByMinutes.get(mode) && minutes < mode)) {
      mode = minutes;
    }
  }
  if (mode === null) return DEFAULT_REPLAY_STEP_MS;
  const fitting = REPLAY_STEPS_MS.filter((step) => step <= mode * MINUTE);
  return fitting[fitting.length - 1];
}

/**
 * Formats a replay step for display, such as "15 min", "6 h" or "1 day".
 *
 * @param {number} stepMs Step in ms.
 * @return {string}
 */
export function formatReplayStep(stepMs) {
  if (stepMs < HOUR) return Math.round(stepMs / MINUTE) + " min";
  if (stepMs < DAY) return Math.round((stepMs / HOUR) * 10) / 10 + " h";
  const days = Math.round((stepMs / DAY) * 10) / 10;
  return days + (days === 1 ? " day" : " days");
}

/**
 * Returns the last step boundary at or before the given time, counting steps from the start.
 *
 * @param {number} time   Time in ms.
 * @param {number} start  Start of the replay in ms.
 * @param {number} stepMs Step in ms.
 * @return {number}       Boundary in ms.
 */
export function stepFloor(time, start, stepMs) {
  return start + Math.floor((time - start) / stepMs) * stepMs;
}

/**
 * Returns the belief time whose data a replay should show.
 *
 * While playing, the data follows the last step boundary the clock has passed.
 * While paused, it catches up with the clock exactly, so the data matches the ruler.
 * Data shown ahead of the last boundary (since a pause, or a switch to a longer step) stays shown until the clock passes the next boundary,
 * rather than being taken back to an earlier belief time.
 *
 * @param {number} position  The replay clock's position, in ms.
 * @param {boolean} playing  Whether the replay clock is running.
 * @param {number} start     Start of the replay in ms.
 * @param {number} stepMs    Step in ms.
 * @param {?number} shown    The belief time whose data is shown, in ms, or null if none is shown yet.
 * @return {number}          Belief time in ms.
 */
export function replayDataTime(position, playing, start, stepMs, shown) {
  if (!playing) return position;
  const boundary = stepFloor(position, start, stepMs);
  if (shown !== null && boundary < shown && shown <= position) return shown;
  return boundary;
}

/**
 * The beliefs known at a belief time that moves forward.
 *
 * The beliefs are sorted by belief time once, and an index walks through them as the belief time advances,
 * so each move costs in proportion to the beliefs it adds, rather than to all beliefs.
 * Per sensor, event and source, only the most recent belief is kept.
 * Moving back in time starts over from the first belief.
 */
export class BeliefTimeline {
  /**
   * @param {Array} beliefs Beliefs, with belief_time in ms, in any order.
   */
  constructor(beliefs) {
    // The sort is stable, so beliefs with the same belief time keep their order, and the last one wins.
    this.beliefs = [...beliefs].sort((a, b) => a.belief_time - b.belief_time);
    this.reset();
  }

  reset() {
    this.next = 0;
    this.latest = new Map();
    this.beliefTime = -Infinity;
  }

  /**
   * Moves to the given belief time.
   *
   * @param {number} beliefTime Belief time in ms.
   * @return {boolean}          Whether the known beliefs changed.
   */
  advanceTo(beliefTime) {
    let changed = false;
    if (beliefTime < this.beliefTime) {
      changed = this.latest.size > 0;
      this.reset();
    }
    while (this.next < this.beliefs.length && this.beliefs[this.next].belief_time <= beliefTime) {
      const belief = this.beliefs[this.next++];
      this.latest.set(beliefKey(belief), belief);
      changed = true;
    }
    this.beliefTime = beliefTime;
    return changed;
  }

  /**
   * @return {Array} The most recent belief per sensor, event and source, known at the current belief time.
   */
  get data() {
    return Array.from(this.latest.values());
  }
}

/**
 * A replay's belief time, tied to the wall clock while playing.
 *
 * The belief time is computed from the wall time elapsed since the clock was last anchored, rather than accumulated per frame,
 * so it advances at a constant rate however long each frame takes to draw:
 * a slow frame delays the next one, but does not slow the replay down.
 */
export class ReplayClock {
  /**
   * @param {number} start Start of the replay in ms.
   * @param {number} end   End of the replay in ms.
   * @param {number} rate  Belief time passing per ms of wall time.
   */
  constructor(start, end, rate) {
    this.start = start;
    this.end = end;
    this.rate = rate;
    this.anchorPosition = start;
    this.anchorWallTime = null; // null while paused
  }

  get playing() {
    return this.anchorWallTime !== null;
  }

  /**
   * @param {number} now Wall time in ms, such as performance.now().
   * @return {number}    Belief time in ms, never past the end.
   */
  position(now) {
    if (!this.playing) return this.anchorPosition;
    return Math.min(this.end, this.anchorPosition + (now - this.anchorWallTime) * this.rate);
  }

  /**
   * Where the clock was last anchored, and how it moves on from there.
   * The anchor changes only when the clock is started, paused, sought or set to another rate,
   * so whatever moves along with the clock by itself needs to hear about it only then.
   *
   * @return {{position: number, wallTime: ?number, rate: number}} The belief time at the wall time, and the rate (0 while paused).
   */
  get anchor() {
    return { position: this.anchorPosition, wallTime: this.anchorWallTime, rate: this.playing ? this.rate : 0 };
  }

  play(now) {
    if (!this.playing) this.anchorWallTime = now;
  }

  pause(now) {
    this.anchorPosition = this.position(now);
    this.anchorWallTime = null;
  }

  setRate(rate, now) {
    // Re-anchor first, so the position does not jump.
    this.anchorPosition = this.position(now);
    if (this.playing) this.anchorWallTime = now;
    this.rate = rate;
  }

  seek(position, now) {
    this.anchorPosition = Math.min(this.end, Math.max(this.start, position));
    if (this.playing) this.anchorWallTime = now;
  }
}
