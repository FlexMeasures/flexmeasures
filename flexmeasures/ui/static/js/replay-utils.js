// Replay utils
export function partition(array, callback){
  return array.reduce(function(result, element, i) {
    callback(element, i, array)
      ? result[0].push(element)
      : result[1].push(element);
      return result;
    }, [[],[]]
  );
};

export function updateBeliefs(oldBeliefs, newBeliefs) {
  // Update oldBeliefs with the most recent newBeliefs about the same event for the same sensor by the same source

  // Group by sensor, event start and source
  var oldBeliefsByEventBySource = Object.fromEntries(new Map(oldBeliefs.map(belief => [belief.sensor.id + '_' + belief.event_start + '_' + belief.source.id, belief])));  // array -> dict (already had one belief per event)

  // Group by sensor, event start and source, and select only the most recent new beliefs
  var mostRecentNewBeliefsByEventBySource = Object.fromEntries(new Map(newBeliefs.map(belief => [belief.sensor.id + '_' + belief.event_start + '_' + belief.source.id, belief])));  // array -> dict (assumes beliefs are ordered by ascending belief time, with the last belief used as dict value)

  // Return old beliefs updated with most recent new beliefs
  return Object.values({...oldBeliefsByEventBySource, ...mostRecentNewBeliefsByEventBySource})  // dict -> list
}
