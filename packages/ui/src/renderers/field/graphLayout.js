// A GSL model's graph laid out as nTop's notebook reads, inputs first and the output last: each name in
// the column after the deepest name it is made from (a longest-path layering), the names of a column in
// the order the model writes them. The graph comes from the field route (`cad.omega._graph`).
//
// A call that returns several values (`mat, col = metal.aluminum();`) is one node with an output port per
// name, and each edge from it leaves the port of the output it carries (the edge's third element). A
// property read or set (`solid.dp`, `bracket.color = col;`) is a small node of its own.

export const COLUMN = 148;
export const ROW = 46;
export const GAP = ROW - 34;
export const NODE = Object.freeze({ width: 120, height: 34 });
// A node with several outputs: its call's name in a header, then one row per output, each with its port.
export const PORT = Object.freeze({ header: 20, row: 14 });
export const PROPERTY_HEIGHT = 22;

/** A node's height: a property's is small, a call with several outputs grows a row per output. */
export function nodeHeight(node) {
  if (node?.kind === "property") return PROPERTY_HEIGHT;
  const outputs = node?.outputs?.length || 0;
  return outputs > 1 ? PORT.header + outputs * PORT.row + 4 : NODE.height;
}

/** Where the output `port` leaves a node, relative to its corner: its row's middle, else the node's middle. */
export function portY(node, port) {
  const at = port == null ? -1 : (node?.outputs || []).indexOf(port);
  return at < 0 ? (node?.height ?? nodeHeight(node)) / 2 : PORT.header + at * PORT.row + PORT.row / 2;
}

/** Each node's column and row, and the drawing's size: `{ nodes: [{ ...node, x, y, height }], edges, width, height }`. */
export function layoutGraph(graph) {
  const nodes = graph?.nodes || [];
  const edges = (graph?.edges || []).filter(([from, to]) => from !== to);
  const into = new Map(nodes.map(node => [node.id, []]));
  for (const [from, to] of edges) if (into.has(to) && into.has(from)) into.get(to).push(from);
  const column = new Map();
  // The model writes a name before it is used (each is assigned once), so one pass in its order layers it.
  for (const node of nodes) column.set(node.id, Math.max(-1, ...into.get(node.id).map(from => column.get(from) ?? -1)) + 1);
  // A block made from nothing (a call such as `metal.aluminum()`) waits in the column before its first use, so its
  // wires (one from each output port) stay short rather than run behind the blocks between; an input stays first.
  const out = new Map(nodes.map(node => [node.id, []]));
  for (const [from, to] of edges) if (out.has(from) && into.has(to)) out.get(from).push(to);
  for (const node of [...nodes].reverse()) {
    if (node.kind === "input" || into.get(node.id).length || !out.get(node.id).length) continue;
    column.set(node.id, Math.max(0, Math.min(...out.get(node.id).map(to => column.get(to))) - 1));
  }
  const rows = new Map();
  const depth = new Map();
  const placed = nodes.map(node => {
    const x = column.get(node.id);
    const row = rows.get(x) || 0;
    const y = depth.get(x) || 0;
    const height = nodeHeight(node);
    rows.set(x, row + 1);
    depth.set(x, y + height + GAP);
    return { ...node, column: x, row, x: x * COLUMN, y, height };
  });
  const columns = Math.max(0, ...placed.map(node => node.column + 1));
  const deepest = Math.max(0, ...depth.values());
  return { nodes: placed, edges: edges.filter(([from, to]) => into.has(from) && into.has(to)),
    width: columns ? (columns - 1) * COLUMN + NODE.width : 0, height: deepest ? deepest - GAP : 0 };
}

/** The curve from one node's right side (the `port` it leaves by, if it has several) to another's left, as a
 * node graph wires a block's output to an input. */
export function wire(from, to, port) {
  const x1 = from.x + NODE.width, y1 = from.y + portY(from, port), x2 = to.x, y2 = to.y + (to.height ?? NODE.height) / 2;
  const bend = Math.max(24, (x2 - x1) / 2);
  return `M${x1} ${y1} C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2} ${y2}`;
}
