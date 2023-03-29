// Replay utils

/**
 * Partitions array into two arrays.
 *
 * Partitions array into two array by pushing elements left or right given some decision function, which is
 * evaluated on each element. Successful validations lead to placement on the left side, others on the right.
 *
 * @param {Array} array               Array to be partitioned.
 * @param {function} decisionFunction Function that assigns elements to the left or right arrays.
 * @return {Array}                    Array containing the left and right arrays.
 */
export function partition(array, decisionFunction){
  return array.reduce(function(result, element, i) {
    decisionFunction(element, i, array)
      ? result[0].push(element)
      : result[1].push(element);
      return result;
    }, [[],[]]
  );
};

/**
 * Updates beliefs.
 *
 * Updates oldBeliefs with the most recent newBeliefs about the same event for the same sensor by the same source.
 *
 * @param {Array} oldBeliefs Array containing old beliefs.
 * @param {Array} newBeliefs Array containing new beliefs.
 * @return {Array}           Array containing updated beliefs.
 */
export function updateBeliefs(oldBeliefs, newBeliefs) {
  // Group by sensor, event start and source
  var oldBeliefsByEventBySource = Object.fromEntries(new Map(oldBeliefs.map(belief => [belief.sensor.id + '_' + belief.event_start + '_' + belief.source.id, belief])));  // array -> dict (already had one belief per event)

  // Group by sensor, event start and source, and select only the most recent new beliefs
  var mostRecentNewBeliefsByEventBySource = Object.fromEntries(new Map(newBeliefs.map(belief => [belief.sensor.id + '_' + belief.event_start + '_' + belief.source.id, belief])));  // array -> dict (assumes beliefs are ordered by ascending belief time, with the last belief used as dict value)

  // Return old beliefs updated with most recent new beliefs
  return Object.values({...oldBeliefsByEventBySource, ...mostRecentNewBeliefsByEventBySource})  // dict -> array
}

//  Define the step duration for the replay (value in ms)
export var beliefTimedelta = 3600000


/**
 * Timer that can be canceled using the optional AbortSignal.
 * Adapted from https://www.bennadel.com/blog/4195-using-abortcontroller-to-debounce-settimeout-calls-in-javascript.htm
 * MIT License: https://www.bennadel.com/blog/license.htm
 */
export function setAbortableTimeout(callback, delayInMilliseconds, signal) {
    signal?.addEventListener( "abort", handleAbort );
    var internalTimer = setTimeout(internalCallback, delayInMilliseconds);

    function internalCallback() {
        signal?.removeEventListener( "abort", handleAbort );
        callback();
    }
    function handleAbort() {
        clearTimeout( internalTimer );
    }
}
