/**
 * Layout of the asset tree shown on the asset context page ("Structure" tab).
 *
 * The page (see `show_tree` in _macros.html) owns the ECharts instance and the zoom interactions;
 * this module turns the flat list of assets into the graph series to draw,
 * so that the layout can be reasoned about, and tested, without a browser page or ECharts.
 *
 * Layout policy, per parent whose children are leaves ("a family"):
 * keep the leaf children in ONE row until the canvas width is exhausted (at the 50px reference box),
 * then use TWO balanced rows (top row at most 1 wider than the bottom), never more;
 * when even two rows don't fit the width, the box size shrinks below the reference,
 * i.e. the whole tree zooms out (wheel-zoom recovers detail).
 * Non-leaf children and the "Add asset" action node each get their own row, recursively.
 *
 * Family connectors are routed to invisible "port" nodes on the top/bottom edge of each leaf box,
 * so top-row connectors arrive from above and bottom-row connectors from below,
 * keeping the lane between the two rows clean.
 * Parents connect from their side.
 */

export const BOX_REF = 50; // reference (minimum comfortable) box size
const GAP_RATIO = 0.28; // vertical gap as a fraction of box size

export const ZOOM_MIN = 0.3;
export const ZOOM_MAX = 2.5;
export const ZOOM_STEP = 0.2;

// The id the server gives the "Add asset" action node (see add_child_asset in views/assets/utils.py).
const ADD_ASSET_ID = "new";

const INVISIBLE = {
  color: "rgba(0,0,0,0)",
  borderWidth: 0,
  shadowBlur: 0,
  shadowColor: "transparent",
  shadowOffsetX: 0,
  shadowOffsetY: 0,
};

/**
 * Keep a zoom factor within the supported range, rounded to hundredths.
 *
 * @param {number} zoom - The zoom factor asked for.
 * @returns {number} - The zoom factor to use.
 */
export function clampZoom(zoom) {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(zoom * 100) / 100));
}

/**
 * Build a hierarchy from the flat list of assets.
 *
 * An asset whose parent is not in the list is shown as a root.
 *
 * @param {Object[]} assets - Assets, each with an `id`, `name` and `parent` (the parent's id, or null).
 * @returns {{assetMap: Object, rootNodes: Object[]}} - The nodes by id, and the roots of the hierarchy.
 */
export function buildAssetHierarchy(assets) {
  const assetMap = {};
  const rootNodes = [];

  assets.forEach((asset) => {
    assetMap[asset.id] = {
      name: asset.name,
      ...asset,
      children: [],
    };
  });

  assets.forEach((asset) => {
    if (asset.parent !== null && asset.parent !== undefined && assetMap[asset.parent]) {
      assetMap[asset.parent].children.push(assetMap[asset.id]);
    } else {
      rootNodes.push(assetMap[asset.id]);
    }
  });

  return { assetMap, rootNodes };
}

/**
 * Wrap a name into at most `maxLines` lines, breaking on spaces where possible and ellipsising the overflow.
 *
 * We do this ourselves rather than rely on ECharts' rich-text width wrapping,
 * which proved unreliable for long names (they would overflow the box horizontally).
 *
 * @param {string} name - The name to wrap.
 * @param {number} charsPerLine - How many characters fit on one line.
 * @param {number} maxLines - How many lines fit in the box.
 * @returns {string} - The lines, joined by newlines.
 */
export function wrapName(name, charsPerLine, maxLines) {
  const words = String(name).split(/\s+/);
  let lines = [];
  let cur = "";
  function pushHardWrapped(word) {
    while (word.length > charsPerLine) {
      lines.push(word.slice(0, charsPerLine));
      word = word.slice(charsPerLine);
    }
    return word;
  }
  for (let i = 0; i < words.length; i++) {
    let w = words[i];
    const candidate = cur ? cur + " " + w : w;
    if (candidate.length <= charsPerLine) {
      cur = candidate;
    } else {
      if (cur) {
        lines.push(cur);
        cur = "";
      }
      if (w.length > charsPerLine) {
        w = pushHardWrapped(w);
      }
      cur = w;
    }
  }
  if (cur) lines.push(cur);
  if (lines.length > maxLines) {
    lines = lines.slice(0, maxLines);
    const last = lines[maxLines - 1];
    lines[maxLines - 1] = last.slice(0, Math.max(1, charsPerLine - 1)).trimEnd() + "…";
  }
  return lines.join("\n");
}

function isAddAsset(node) {
  return node.id === ADD_ASSET_ID;
}

// Leaf children go into the family grid; internal children and the "Add asset" button each get their own row.
function splitKids(node) {
  const kids = node.children || [];
  return {
    gridKids: kids.filter((k) => !(k.children || []).length && !isAddAsset(k)),
    rowKids: kids.filter((k) => (k.children || []).length || isAddAsset(k)),
  };
}

function depthOf(node) {
  let d = 0;
  (node.children || []).forEach((k) => {
    d = Math.max(d, 1 + depthOf(k));
  });
  return d;
}

/**
 * Lay out the tree and return the ECharts option that draws it.
 *
 * Zoom is applied by re-rendering the tree at a new scale (node sizes + layout margins)
 * while the canvas stays a fixed size,
 * so the tree shrinks or grows within the gray area like a map, and the area itself never changes size.
 *
 * @param {Object[]} rootNodes - Roots of the hierarchy, as returned by buildAssetHierarchy.
 * @param {Object} assetMap - Nodes by id, as returned by buildAssetHierarchy.
 * @param {Object} options
 * @param {number} options.width - Width of the canvas, in pixels.
 * @param {number} options.viewportHeight - Height of the canvas, in pixels.
 * @param {number} [options.zoomFactor] - Current zoom level.
 * @param {*} [options.currentAssetId] - Id of the asset whose page this is, which is highlighted.
 * @param {boolean} [options.animate] - Pass false to skip the update animation, e.g. during continuous wheel-zoom.
 * @returns {Object} - The ECharts option.
 */
export function buildAssetTreeOption(rootNodes, assetMap, options) {
  const { width: W, viewportHeight: viewportH, zoomFactor = 1, currentAssetId, animate } = options;

  // One x position per tree level (ancestors -> current -> children -> grandchildren);
  // the deepest level's grid columns extend to the right from there.
  let levels = 1;
  rootNodes.forEach((rt) => {
    levels = Math.max(levels, 1 + depthOf(rt));
  });
  const colPitch = levels > 1 ? Math.min((0.6 * W) / (levels - 1), 0.3 * W) : 0;
  function colX(d) {
    return 0.08 * W + d * colPitch;
  }

  // Horizontal room for a grid block whose leaf column sits at level d.
  function gridBudget(d) {
    return W - colX(d) - 8;
  }
  function colsFitAt(d) {
    return Math.max(1, Math.floor((gridBudget(d) - BOX_REF * 0.5) / (BOX_REF * 1.35)) + 1);
  }
  // One row while it fits; else two balanced rows, top at most 1 wider.
  function colsFor(n, d) {
    if (!n) return 1;
    const fit = colsFitAt(d);
    return n <= fit ? n : Math.ceil(n / 2);
  }

  // Pre-pass: total rows (drives the vertical fit) and the widest grid block (drives the horizontal cap on the box size).
  let hCap = Infinity;
  function rowsOf(node, d) {
    const s = splitKids(node);
    if (!s.gridKids.length && !s.rowKids.length) return 1;
    let r = 0;
    if (s.gridKids.length) {
      const cols = colsFor(s.gridKids.length, d + 1);
      r += Math.ceil(s.gridKids.length / cols);
      hCap = Math.min(hCap, gridBudget(d + 1) / ((cols - 1) * 1.35 + 0.5));
    }
    s.rowKids.forEach((k) => {
      r += rowsOf(k, d + 1);
    });
    return Math.max(r, 1);
  }
  let totalRows = 0;
  rootNodes.forEach((rt) => {
    totalRows += rowsOf(rt, 0);
  });

  // Box size: fit the viewport vertically, clamped to a legible range,
  // then capped so the widest grid block still fits the width.
  // Two rows is the maximum,
  // so very wide families lower the box size (the tree zooms out) instead of wrapping further.
  const fitBox = (viewportH * 0.92) / Math.max(totalRows + 1, 5) / (1 + GAP_RATIO);
  const BOX_SIZE = Math.round(
    Math.min(Math.max(BOX_REF, Math.min(104, fitBox)), Math.max(20, hCap))
  );
  const slotY = BOX_SIZE * (1 + GAP_RATIO); // vertical row pitch
  const colGapX = BOX_SIZE * 1.35; // horizontal grid column pitch
  const blockGap = slotY * 0.55; // gap between family blocks

  // Labels (text + icon) are drawn by ECharts at a fixed on-screen size, unaffected by the view's zoom transform,
  // so derive all label metrics from the EFFECTIVE on-screen box size instead.
  // Since every zoom step re-renders, zooming in re-wraps names at a larger, more legible size,
  // and zooming out shrinks them with the box instead of letting them pour out of it.
  const BOX_EFF = BOX_SIZE * zoomFactor;
  const SHOW_LABELS = BOX_EFF >= 24; // below this, text is just noise
  const ICON_SIZE = Math.max(4, Math.floor(BOX_EFF * 0.26));
  const FONT_SIZE = Math.max(6, Math.round(BOX_EFF * 0.13));
  const LINE_H = FONT_SIZE + 2;

  // How many text lines fit under the icon, inside the box?
  const textBudget = BOX_EFF - ICON_SIZE - 10;
  const MAX_LINES = Math.min(3, Math.max(1, Math.floor(textBudget / LINE_H)));
  // Approx chars per line at this font (~0.56em average glyph width).
  const charsPerLine = Math.max(4, Math.floor((BOX_EFF - 12) / (FONT_SIZE * 0.56)));

  // Per-node style: white round rects, gold current asset, green "Add asset" button.
  function nodeStyles(node) {
    const isCurrent = node.id === currentAssetId;
    const isAdd = isAddAsset(node);

    const displayName = wrapName(node.name, charsPerLine, MAX_LINES);
    const rich = {
      text: {
        width: BOX_EFF - 6,
        overflow: "truncate",
        align: "center",
        fontSize: FONT_SIZE,
        lineHeight: LINE_H,
        padding: [2, 0, 0, 0],
      },
    };
    if (node.icon) {
      rich["icon_" + node.id] = {
        backgroundColor: { image: node.icon },
        height: ICON_SIZE,
        width: ICON_SIZE,
        align: "center",
      };
    }

    return {
      symbol: "roundRect",
      symbolSize: isCurrent ? [BOX_SIZE * 1.08, BOX_SIZE * 1.08] : [BOX_SIZE, BOX_SIZE],
      label: {
        show: SHOW_LABELS,
        position: "inside",
        color: isCurrent ? "#000000" : isAdd ? "#ffffff" : "#1e293b",
        fontSize: FONT_SIZE,
        fontWeight: isCurrent ? "bold" : "600",
        fontFamily: "system-ui, -apple-system, sans-serif",
        // A function rather than a template string,
        // so that ECharts does not substitute its template variables ({a}, {b}, {c}) in asset names.
        formatter: () =>
          node.icon
            ? "{icon_" + node.id + "|}\n{text|" + displayName + "}"
            : "{text|" + displayName + "}",
        rich: rich,
      },
      itemStyle: {
        color: isCurrent ? "#fcd34d" : isAdd ? "#10b981" : "#ffffff",
        borderColor: isCurrent ? "#f59e0b" : isAdd ? "#047857" : "#cbd5e1",
        borderWidth: isCurrent ? 3 : 1,
        borderRadius: 8,
        shadowColor: "rgba(0, 0, 0, 0.2)",
        shadowBlur: 10,
        shadowOffsetX: 2,
        shadowOffsetY: 6,
      },
    };
  }

  const nodes = [];
  const links = [];

  // Place a node; if `port` is given, route the connector from the parent to an invisible port node
  // on the box's top/bottom edge instead of to the box itself.
  function pushNode(node, x, y, port) {
    nodes.push(
      Object.assign(
        {
          id: String(node.id),
          name: node.name,
          x: x,
          y: y,
          link: node.link,
          tooltip: node.tooltip,
        },
        nodeStyles(node)
      )
    );
    if (node.parent === undefined || node.parent === null || !assetMap[node.parent]) {
      return;
    }
    if (port) {
      const pid = "port-" + node.id;
      nodes.push({
        id: pid,
        name: "",
        x: port.x,
        y: port.y,
        symbol: "circle",
        symbolSize: 0.1,
        silent: true,
        label: { show: false },
        itemStyle: INVISIBLE,
      });
      links.push({
        source: String(node.parent),
        target: pid,
        lineStyle: { curveness: port.curveness },
      });
    } else {
      links.push({ source: String(node.parent), target: String(node.id) });
    }
  }

  // Recursively lay out `node` (at tree level `d`) and its subtree, starting at vertical offset topY.
  // Returns the block height and the node's own center y.
  function layoutSubtree(node, d, topY) {
    const s = splitKids(node);
    if (!s.gridKids.length && !s.rowKids.length) {
      const cy = topY + slotY / 2;
      pushNode(node, colX(d), cy);
      return { height: slotY, centerY: cy };
    }
    let y = topY;
    const centers = [];
    if (s.gridKids.length) {
      const cols = colsFor(s.gridKids.length, d + 1);
      const rows = Math.ceil(s.gridKids.length / cols);
      s.gridKids.forEach((k, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        const x = colX(d + 1) + col * colGapX;
        const ky = y + slotY / 2 + row * slotY;
        const topRow = row === 0;
        pushNode(k, x, ky, {
          x: x,
          y: topRow ? ky - BOX_SIZE / 2 : ky + BOX_SIZE / 2,
          curveness: topRow ? 0.18 : -0.18,
        });
      });
      const blockH = rows * slotY;
      centers.push(y + blockH / 2);
      y += blockH + blockGap;
    }
    s.rowKids.forEach((k) => {
      const sub = layoutSubtree(k, d + 1, y);
      centers.push(sub.centerY);
      y += sub.height + blockGap;
    });
    y -= blockGap; // drop the trailing gap
    const centerY = centers.reduce((a, b) => a + b, 0) / centers.length;
    pushNode(node, colX(d), centerY);
    return { height: y - topY, centerY: centerY };
  }

  let cursorY = slotY * 0.5;
  rootNodes.forEach((rt) => {
    cursorY += layoutSubtree(rt, 0, cursorY).height + blockGap;
  });
  const contentH = cursorY - blockGap + slotY * 0.5;

  // Invisible pin nodes make the layout's bounding box deterministic:
  // exactly the canvas width by at least the viewport height.
  // The graph view fits that box into the canvas,
  // so the transform is identity while the content fits, and a uniform zoom-out once the content is taller than the viewport.
  [
    [0, 0],
    [W, Math.max(contentH, viewportH)],
  ].forEach((p, i) => {
    nodes.push({
      id: "__pin" + i,
      name: "",
      x: p[0],
      y: p[1],
      symbol: "circle",
      symbolSize: 0.1,
      silent: true,
      label: { show: false },
      itemStyle: INVISIBLE,
    });
  });

  return {
    tooltip: {
      trigger: "item",
      triggerOn: "mousemove",
      backgroundColor: "rgba(255, 255, 255, 0.95)",
      borderColor: "#e2e8f0",
      borderWidth: 1,
      textStyle: { color: "#334155" },
      formatter: function (params) {
        return params.data.tooltip || params.name;
      },
    },
    series: [
      {
        type: "graph",
        layout: "none",
        data: nodes,
        links: links,
        // Drag to pan; wheel and +/- buttons drive series.zoom.
        roam: "move",
        zoom: zoomFactor,
        // Scale node symbols 1:1 with the view zoom.
        nodeScaleRatio: 1,
        edgeSymbol: ["none", "none"],
        animationDuration: 550,
        // No update animation during continuous wheel-zoom, so the tree follows the wheel without lagging behind.
        animationDurationUpdate: animate === false ? 0 : 400,
        lineStyle: {
          color: "#94a3b8",
          width: 2,
          curveness: 0.15,
        },
      },
    ],
  };
}
