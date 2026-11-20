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

// Wall time in ms over which a paused replay's ruler glides to a stop:
// long enough for the browser to get word of the pause before the ruler, moving by itself, gets there.
export const REPLAY_PAUSE_GLIDE_MS = 50;

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
    this.glide = null; // how the clock moved up to where it was paused, while that is still of use
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
   * How the clock moves from where it was last anchored, for whatever moves along with it by itself, such as a ruler.
   * The motion changes only when the clock is started, paused, sought or set to another rate,
   * so whatever moves along with the clock needs to hear about it only then.
   *
   * While playing, the motion runs from the anchor at the rate, up to the end of the replay.
   * Right after a pause, it is the motion the clock had, up to where it was paused, so that what moves along glides to a stop there.
   * Otherwise, it stands still where the clock was paused.
   *
   * @return {{position: number, wallTime: ?number, rate: number, end: number}} The belief time at the wall time, the rate (0 when standing still), and where the motion stops.
   */
  get motion() {
    if (this.playing) return { position: this.anchorPosition, wallTime: this.anchorWallTime, rate: this.rate, end: this.end };
    if (this.glide) return { ...this.glide, end: this.anchorPosition };
    return { position: this.anchorPosition, wallTime: null, rate: 0, end: this.anchorPosition };
  }

  play(now) {
    if (!this.playing) this.anchorWallTime = now;
    this.glide = null;
  }

  /**
   * Pauses the clock, possibly a little ahead of the given wall time.
   *
   * Whatever moves along with the clock by itself (see motion) may already have moved on before it hears about the pause,
   * and pausing where it already went would make it jump back.
   * Pausing slightly ahead lets it glide to a stop instead.
   *
   * @param {number} now          Wall time in ms.
   * @param {number} [glideMs=0]  How much later, in wall time, to pause the clock.
   */
  pause(now, glideMs = 0) {
    if (this.playing) this.glide = glideMs > 0 ? { position: this.anchorPosition, wallTime: this.anchorWallTime, rate: this.rate } : null;
    this.anchorPosition = this.position(now + glideMs);
    this.anchorWallTime = null;
  }

  /**
   * @param {number} now Wall time in ms.
   * @return {boolean}   Whether the clock is still gliding to a stop after a pause, according to its motion.
   */
  gliding(now) {
    const motion = this.motion;
    return !this.playing && motion.rate > 0 && motion.position + (now - motion.wallTime) * motion.rate < motion.end;
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
    this.glide = null;
  }
}

/**
 * The durations of the last few data redraws, to tell how long the next one will take at least.
 *
 * A replay draws its data for the belief time at which the redraw is expected to show up on screen, rather than when it starts,
 * so that the data keeps up with the ruler.
 * Expecting the shortest recent duration keeps the data from getting ahead of the ruler, unless a redraw is quicker than all of those.
 */
export class RedrawDurations {
  /**
   * @param {number} [size=5] How many recent durations to remember.
   */
  constructor(size = 5) {
    this.size = size;
    this.durations = [];
  }

  /**
   * @param {number} ms How long a redraw took, in ms.
   */
  add(ms) {
    this.durations.push(ms);
    if (this.durations.length > this.size) this.durations.shift();
  }

  /**
   * @return {number} The shortest recent duration in ms, or 0 before any redraw.
   */
  get shortest() {
    return this.durations.length ? Math.min(...this.durations) : 0;
  }
}
