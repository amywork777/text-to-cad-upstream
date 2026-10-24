// The drawings of GD&T's symbols, on the 24-unit grid every glyph of the viewer is drawn on
// (`kit/tools/select/modeGlyphs.jsx`), stroked in the current colour. Drawn, not typed: the
// characteristic symbols (U+2300 block, U+27C2) are missing from most UI fonts, and a fallback
// font would set each one at its own size and weight inside a feature control frame's cell.

const SVG = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };

const GLYPHS = Object.freeze({
  // ASME Y14.5 / ISO 1101 characteristics, the ones a frame of the supported subset can carry.
  flatness: <path d="M3.5 17 8 7h12.5L16 17Z" />,
  position: <><circle cx="12" cy="12" r="5.5" /><path d="M12 3v18M3 12h18" /></>,
  // A frame's tolerance zone and a dimension's diameter: a circle struck through.
  diameter: <><circle cx="12" cy="12" r="6.5" /><path d="M5.5 18.5 18.5 5.5" /></>,
  // Datum feature symbol: the filled triangle a datum's leader stands on.
  datum: <path d="M5 18h14l-7-11Z" fill="currentColor" />,
  // A dimension: two extension lines and the line between them, its arrowheads.
  dimension: <><path d="M4 5v14M20 5v14M4 12h16" /><path d="m7 9-3 3 3 3M17 9l3 3-3 3" /></>,
  // A frame: two cells, a row of a frame's kind (the PMI section's tile too, `PmiIcon`).
  frame: <><rect x="2.5" y="7" width="19" height="10" rx="1" /><path d="M9.5 7v10" /></>,
  // What the viewer does not draw: a frame with a question in it.
  unsupported: <><rect x="3" y="5" width="18" height="14" rx="1.5" strokeDasharray="2.5 2.5" /><path d="M10 10a2 2 0 1 1 2.5 1.9c-.4.2-.5.5-.5.9v.4M12 16h.01" /></>,
});

/** One of `GLYPHS` by name; nothing for a name it has none for. */
export function PmiGlyph({ name, ...props }) {
  const glyph = GLYPHS[name];
  if (!glyph) return null;
  return <svg {...SVG} data-pmi-glyph={name} {...props}>{glyph}</svg>;
}

/** The PMI section's icon, its file sidebar tile and tab (`ToolPanel`'s `icon`): a feature control frame. */
export function PmiIcon(props) {
  return <PmiGlyph name="frame" {...props} />;
}
