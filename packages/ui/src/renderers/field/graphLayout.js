// A GSL model's graph laid out as nTop's notebook reads, inputs first and the output last: each name in
// the column after the deepest name it is made from (a longest-path layering), the names of a column in
// the order the model writes them. The graph comes from the field route (`cad.omega._graph`).

export const COLUMN = 148;
export const ROW = 46;
export const NODE = Object.freeze({ width: 120, height: 34 });

/** Each node's column and row, and the drawing's size: `{ nodes: [{ ...node, x, y }], edges, width, height }`. */
export function layoutGraph(graph) {
  const nodes = graph?.nodes || [];
  const edges = (graph?.edges || []).filter(([from, to]) => from !== to);
  const into = new Map(nodes.map(node => [node.id, []]));
  for (const [from, to] of edges) if (into.has(to) && into.has(from)) into.get(to).push(from);
  const column = new Map();
  // The model writes a name before it is used (each is assigned once), so one pass in its order layers it.
  for (const node of nodes) column.set(node.id, Math.max(-1, ...into.get(node.id).map(from => column.get(from) ?? -1)) + 1);
  const rows = new Map();
  const placed = nodes.map(node => {
    const x = column.get(node.id);
    const y = rows.get(x) || 0;
    rows.set(x, y + 1);
    return { ...node, column: x, row: y, x: x * COLUMN, y: y * ROW };
  });
  const columns = Math.max(0, ...placed.map(node => node.column + 1));
  const deepest = Math.max(0, ...rows.values());
  return { nodes: placed, edges: edges.filter(([from, to]) => into.has(from) && into.has(to)),
    width: columns ? (columns - 1) * COLUMN + NODE.width : 0, height: deepest ? (deepest - 1) * ROW + NODE.height : 0 };
}

/** The curve from one node's right side to another's left, as a node graph wires a block's output to an input. */
export function wire(from, to) {
  const x1 = from.x + NODE.width, y1 = from.y + NODE.height / 2, x2 = to.x, y2 = to.y + NODE.height / 2;
  const bend = Math.max(24, (x2 - x1) / 2);
  return `M${x1} ${y1} C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2} ${y2}`;
}
