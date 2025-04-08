
// Useful functions for our asset-specific Leaflet code

function addTileLayer(leafletMap, mapboxAccessToken) {
    /*
    Add the tile layer for FlexMeasures.
    Configure tile size, Mapbox API access and attribution.
    */
    var tileLayer = new L.tileLayer('https://api.mapbox.com/styles/v1/{id}/tiles/{z}/{x}/{y}?access_token={accessToken}', {
        attribution: '© <a href="https://www.mapbox.com/about/maps/">Mapbox</a> © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> <strong><a href="https://www.mapbox.com/map-feedback/" target="_blank">Improve this map</a></strong>',
        tileSize: 512,
        maxZoom: 18,
        zoomOffset: -1,
        id: 'mapbox/streets-v11',
        accessToken: mapboxAccessToken
    });
    tileLayer.addTo(leafletMap);
    // add link for Mapbox logo (logo added via CSS)
    $("#" + leafletMap._container.id).append(
        '<a href="https://mapbox.com/about/maps" class="mapbox-logo" target="_blank">Mapbox</a>'
    );
}


function clickPan(e, data) {
    // set view such that the target asset lies slightly below the center of the map
    targetLatLng = e.target.getLatLng()
    targetZoom = assetMap.getZoom()
    targetPoint = assetMap.project(targetLatLng, targetZoom).subtract([0, 50]),
    targetLatLng = assetMap.unproject(targetPoint, targetZoom);
    assetMap.setView(targetLatLng, targetZoom);
}


/**
 * Injects a custom spiderfy layout function into the marker cluster, passing both
 * child markers and the cluster center point to the layout function.
 *
 * @param {L.MarkerCluster} markerCluster - The marker cluster instance to modify.
 */
function passMarkersToSpiderfyShapePositions (markerCluster) {
    const childMarkers = markerCluster.getAllChildMarkers();
    const centerPt = markerCluster._group._map.latLngToLayerPoint(markerCluster._latlng);
    const shapeFn = markerCluster._group?.options?.spiderfyShapePositionsWithMarkers;
    if (typeof shapeFn === 'function') {
        markerCluster._group.options.spiderfyShapePositions = () =>
            shapeFn(childMarkers, centerPt);
    }
}


/**
 * Removes all spider legs (connecting lines) from the map for the given marker cluster.
 *
 * @param {L.MarkerCluster} markerCluster - The marker cluster from which to remove spider legs.
 */
function removeSpiderLegs(markerCluster) {
    const map = markerCluster._group._map;
    for (const marker of markerCluster.getAllChildMarkers()) {
        if (marker._spiderLeg) {
            map.removeLayer(marker._spiderLeg);
        }
    }
}


/**
 * Computes a tree-based layout for markers, organizing them into a forest centered
 * around a given point. Markers must have `id` and `parentId` options.
 *
 * @param {Array<L.Marker>} markers - Array of markers with hierarchical relationships.
 * @param {L.Point} centerPt - The center point to base the layout around.
 * @param {number} [spacingX=50] - Horizontal spacing between sibling nodes.
 * @param {number} [spacingY=100] - Vertical spacing between levels.
 * @param {number} [treeSpacing=100] - Spacing between root trees.
 * @returns {Array<L.Point>} Array of new positions (as layer points) for the markers.
 */
function computeCenteredTreeLayout(markers, centerPt, spacingX = 50, spacingY = 100, treeSpacing = 100) {
    const nodeMap = new Map();

    // Add virtual parent nodes if they are missing a marker (no lat/lng)
    const allParentIds = new Set(markers.map(m => m.options.parentId).filter(id => id !== null));
    for (const parentId of allParentIds) {
        if (!nodeMap.has(parentId)) {
            // Use the first child with this parent to determine location
            const child = markers.find(m => m.options.parentId === parentId);
            if (child) {
                nodeMap.set(parentId, {
                    id: parentId,
                    parentId: null,
                    children: [],
                    x: 0,
                    y: 0,
                    virtual: true // you can tag it if needed
                });
            }
        }
    }

    markers.forEach(marker => {
        const { id, parentId } = marker.options;
        nodeMap.set(id, { ...marker.options, children: [], x: 0, y: 0 });
    });

    let roots = [];
    nodeMap.forEach(node => {
        if (node.parentId === null) {
            roots.push(node);
        } else {
            const parent = nodeMap.get(node.parentId);
            if (parent) {
                parent.children.push(node);
            }
        }
    });

    const positionMap = new Map(); // id -> { dx, dy, level }
    let currentX = 0;

    function layoutTree(node, depth) {
        if (node.children.length === 0) {
            node.x = currentX;
            currentX += spacingX;
        } else {
            for (const child of node.children) {
                layoutTree(child, depth + 1);
            }
            const xs = node.children.map(child => child.x);
            node.x = (Math.min(...xs) + Math.max(...xs)) / 2;
        }
        node.y = depth * spacingY;
        positionMap.set(node.id, { dx: node.x, dy: node.y, level: depth });
    }

    let globalXOffset = 0;

    for (const root of roots) {
        const startX = currentX;
        layoutTree(root, 0);

        // Adjust all dx in this tree by (startX - minX)
        const treeNodes = [...nodeMap.values()].filter(n => positionMap.has(n.id));
        const minX = Math.min(...treeNodes.map(n => positionMap.get(n.id).dx));
        const offset = startX - minX;
        for (const n of treeNodes) {
            const pos = positionMap.get(n.id);
            pos.dx += offset;
        }

        // Update currentX for next tree
        const maxX = Math.max(...treeNodes.map(n => positionMap.get(n.id).dx));
        currentX = maxX + treeSpacing;
    }

    // === Center the forest around (0, 0) ===

    const allPositions = Array.from(positionMap.values());

    const minDx = Math.min(...allPositions.map(p => p.dx));
    const maxDx = Math.max(...allPositions.map(p => p.dx));
    const centerX = (minDx + maxDx) / 2;

    const maxLevel = Math.max(...allPositions.map(p => p.level));
    const centerLevel = maxLevel / 2;
    const centerY = centerLevel * spacingY;

    for (const pos of allPositions) {
        pos.dx -= centerX;
        pos.dy -= centerY;
    }

    // Final result in original order
    return markers.map(marker => {
        const { dx, dy } = positionMap.get(marker.options.id);
        // console.log(marker.options.id, ": ", dx, ", ", dy);
        return L.point(
            {
                x: centerPt.x + dx,
                y: centerPt.y + dy
            }
        );
    });
}


/**
 * Performs a tree-style animated spiderfy for a cluster, using parent-child relationships
 * between markers to create animated spider legs from parent to child.
 *
 * @param {Array<L.Marker>} childMarkers - The markers to be spiderfied.
 * @param {Array<L.Point>} positions - The target layer point positions for the markers.
 */
function _animationTreeSpiderfy(childMarkers, positions) {
    var me = this,
        group = this._group,
        map = group._map,
        fg = group._featureGroup,
        thisLayerLatLng = this._latlng,
        thisLayerPos = map.latLngToLayerPoint(thisLayerLatLng),
        svg = L.Path.SVG,
        legOptions = L.extend({}, this._group.options.spiderLegPolylineOptions), // Copy the options so that we can modify them for animation.
        finalLegOpacity = legOptions.opacity,
        i, m, leg, legPath, legLength, newPos;

    if (finalLegOpacity === undefined) {
        finalLegOpacity = L.MarkerClusterGroup.prototype.options.spiderLegPolylineOptions.opacity;
    }

    if (svg) {
        // If the initial opacity of the spider leg is not 0 then it appears before the animation starts.
        legOptions.opacity = 0;

        // Add the class for CSS transitions.
        legOptions.className = (legOptions.className || '') + ' leaflet-cluster-spider-leg';
    } else {
        // Make sure we have a defined opacity.
        // legOptions.opacity = finalLegOpacity;
        legOptions.opacity = 0;  // Seita monkeypatch
    }

    group._ignoreMove = true;

    // Seita monkeypatch
    // Build a quick lookup map by marker id
    const markerMap = new Map(childMarkers.map(m => [m.options.id, m]));

    // Add markers and spider legs to map, hidden at our center point.
    // Traverse in ascending order to make sure that inner circleMarkers are on top of further legs. Normal markers are re-ordered by newPosition.
    // The reverse order trick no longer improves performance on modern browsers.
    for (i = 0; i < childMarkers.length; i++) {
        m = childMarkers[i];
        childPos = positions[i]

         // Seita monkeypatch
        const parentId = m.options.parentId;
        var hasParentPos = true;
        if (parentId == null) {
            hasParentPos = false;
        };
        const parentMarker = markerMap.get(parentId);
        if (!parentMarker) {
            hasParentPos = false;
        };
        const parentPos = positions[childMarkers.indexOf(parentMarker)];
        if (!parentPos) {
            hasParentPos = false;
        };

        newPos = map.layerPointToLatLng(positions[i]);
        if (hasParentPos == true) {
            oldPos = map.layerPointToLatLng(parentPos);
        } else {
            oldPos = newPos;
        }

        // Add the leg before the marker, so that in case the latter is a circleMarker, the leg is behind it.
        leg = new L.Polyline([oldPos, newPos], legOptions);
        // leg = new L.Polyline([thisLayerLatLng, newPos], legOptions);
        map.addLayer(leg);
        m._spiderLeg = leg;

        // Explanations: https://jakearchibald.com/2013/animated-line-drawing-svg/
        // In our case the transition property is declared in the CSS file.
        if (svg) {
            legPath = leg._path;
            legLength = legPath.getTotalLength() + 0.1; // Need a small extra length to avoid remaining dot in Firefox.
            legPath.style.strokeDasharray = legLength; // Just 1 length is enough, it will be duplicated.
            legPath.style.strokeDashoffset = legLength;
        }
    }
    for (i = 0; i < childMarkers.length; i++) {
        m = childMarkers[i];
        // If it is a marker, add it now and we'll animate it out
        if (m.setZIndexOffset) {
            m.setZIndexOffset(1000000); // Make normal markers appear on top of EVERYTHING
        }
        if (m.clusterHide) {
            m.clusterHide();
        }

        // Vectors just get immediately added
        fg.addLayer(m);

        if (m._setPos) {
            m._setPos(thisLayerPos);
        }
    }

    group._forceLayout();
    group._animationStart();

    // Reveal markers and spider legs.
    for (i = childMarkers.length - 1; i >= 0; i--) {
        newPos = map.layerPointToLatLng(positions[i]);
        m = childMarkers[i];

        //Move marker to new position
        m._preSpiderfyLatlng = m._latlng;
        m.setLatLng(newPos);

        if (m.clusterShow) {
            m.clusterShow();
        }

        // Animate leg (animation is actually delegated to CSS transition).
        if (svg) {
            leg = m._spiderLeg;
            legPath = leg._path;
            legPath.style.strokeDashoffset = 0;
            //legPath.style.strokeOpacity = finalLegOpacity;
            leg.setStyle({opacity: finalLegOpacity});
        }
    }
    this.setOpacity(0.3);

    group._ignoreMove = false;

    setTimeout(function () {
        group._animationEnd();
        group.fire('spiderfied', {
            cluster: me,
            markers: childMarkers
        });

        // Seita monkeypatch
        for (i = childMarkers.length - 1; i >= 0; i--) {
            m = childMarkers[i];
            leg = m._spiderLeg;
            leg.setStyle({opacity: finalLegOpacity});
        }
    }, 200);
}