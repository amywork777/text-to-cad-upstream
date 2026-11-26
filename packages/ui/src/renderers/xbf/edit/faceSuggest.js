/**
 * What two faces picked together suggest doing with them, read off their surfaces as the scene has them (`elementGeometry`:
 * a plane's normal and a point on it, a cylinder's axis, a point on it and its radius): the selection bar's second row
 * (`EditSelectionBar.jsx`), as SolidWorks' context toolbar offers what fits the picks. Pure: `useXbfCadMode.jsx` wires each
 * suggestion to what does it.
 *
 * Each suggestion is `{ id, kind, label, hint, ... }`, by kind:
 * - `reading`: what the two measure, said and not pressed (two flat faces' gap or angle, two coaxial round faces' sizes);
 * - `command`: a modeling command (`command`: "fillet", "chamfer") opened on the edges the two faces share (`edges`);
 * - `mate`: Mate opened on the two faces of two parts, starting as `mateType`;
 * - `ask`: the agent asked, in the chat box, to do it (`request`), with the faces carried;
 * - `preview`: shown to say where it would go, not wired to anything yet: the bar marks it so.
 */

const PARALLEL = 0.9995;

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const length = a => Math.hypot(a[0], a[1], a[2]);
const isPoint = value => Array.isArray(value) && value.length >= 3 && value.slice(0, 3).every(Number.isFinite);

/** A length in the part's units, as a drawing writes it: up to three places, no trailing zeros. */
export function lengthText(value, units = "mm") {
  const places = units === "in" ? 3 : 2;
  const text = Number(value.toFixed(places)).toString();
  return units === "in" ? `${text} in` : `${text} mm`;
}

/** The distance from a point to a line through `origin` along unit `axis`. */
const fromAxis = (point, origin, axis) => length(cross(sub(point, origin), axis));

/**
 * The suggestions for two faces, each `{ id, surface, instance }` (`surface` as `elementGeometry` gives it, `instance` the part
 * it is on), or none for anything but two faces the scene can describe. `shared`: the ids of the edges they share (a face's
 * own edges: `scene.sharedEdges`), which makes them a corner to round or bevel. `assembly`: they are in an assembly, where
 * two parts' faces are mated rather than modeled. `units`: the part's.
 *
 * @param {{ faces: { id: string, surface: object | null, instance: number }[], shared?: string[], assembly?: boolean,
 *   units?: string }} input
 */
export function faceSuggestions({ faces, shared = [], assembly = false, units = "mm" }) {
  if (faces?.length !== 2) return [];
  const [a, b] = faces.map(face => face.surface);
  if (!a || !b) return [];
  const twoParts = assembly && faces[0].instance !== faces[1].instance;
  const corner = !assembly && shared.length > 0
    ? [
      { id: "fillet", kind: "command", command: "fillet", edges: shared, label: "Fillet", hint: "Round the edge these faces share" },
      { id: "chamfer", kind: "command", command: "chamfer", edges: shared, label: "Chamfer", hint: "Bevel the edge these faces share" },
    ]
    : [];
  const mate = (mateType, label) => (twoParts
    ? [{ id: "mate", kind: "mate", mateType, label, hint: "Mate these two parts' faces" }]
    : []);

  if (a.type === "plane" && b.type === "plane" && isPoint(a.normal) && isPoint(b.normal)) {
    const cos = dot(a.normal, b.normal);
    if (Math.abs(cos) >= PARALLEL && isPoint(a.origin) && isPoint(b.origin)) {
      const gap = Math.abs(dot(sub(b.origin, a.origin), a.normal));
      const flush = gap < 1e-6;
      return [
        { id: "distance", kind: "reading", label: flush ? "Flush" : `${lengthText(gap, units)} apart`, hint: "Between the two flat faces, square across" },
        ...mate(flush ? "coincident" : "distance", flush ? "Mate coincident" : "Mate at distance"),
        ...(twoParts || assembly ? [] : [{ id: "set-distance", kind: "preview", label: "Set distance", hint: "Change the size between these faces" }]),
      ];
    }
    const degrees = Math.acos(Math.min(1, Math.abs(cos))) * 180 / Math.PI;
    const square = Math.abs(degrees - 90) < 0.05;
    return [
      { id: "angle", kind: "reading", label: square ? "Square" : `${Number(degrees.toFixed(1))}°`, hint: "The angle between the two flat faces" },
      ...corner,
      ...mate(square ? "perpendicular" : "angle", square ? "Mate perpendicular" : "Mate at angle"),
    ];
  }

  if (a.type === "cylinder" && b.type === "cylinder" && isPoint(a.axis) && isPoint(b.axis) && isPoint(a.origin) && isPoint(b.origin)
    && a.radius > 0 && b.radius > 0) {
    const coaxial = Math.abs(dot(a.axis, b.axis)) >= PARALLEL && fromAxis(b.origin, a.origin, a.axis) < Math.max(a.radius, b.radius) * 1e-3;
    if (!coaxial) return corner;
    const [small, large] = [a.radius, b.radius].sort((x, y) => x - y);
    const sizes = small === large ? `Ø${lengthText(2 * small, units)}` : `Ø${lengthText(2 * small, units)} in Ø${lengthText(2 * large, units)}`;
    // A hole and the shaft in it: sizes within a tenth of each other, the nominal the hole's as modelled.
    const fits = units !== "in" && large - small <= large * 0.1;
    const nominal = Number((2 * large).toFixed(2));
    return [
      { id: "coaxial", kind: "reading", label: `Coaxial, ${sizes}`, hint: "Two round faces on one axis" },
      ...(fits ? [{
        id: "iso-fit", kind: "ask", label: "ISO fit…", hint: "Ask for a hole and shaft fit from ISO 286",
        request: `Put an ISO fit on these two faces, a Ø${nominal} mm hole and the shaft in it.`,
      }] : []),
      ...mate("concentric", "Mate concentric"),
      ...corner,
    ];
  }

  const plane = a.type === "plane" ? a : b.type === "plane" ? b : null;
  const round = a.type === "cylinder" ? a : b.type === "cylinder" ? b : null;
  if (plane && round && isPoint(plane.normal) && isPoint(round.axis)) {
    const across = Math.abs(dot(plane.normal, round.axis));
    return [
      ...(across >= PARALLEL ? [{ id: "square", kind: "reading", label: "Axis square to face", hint: "The round face's axis is normal to the flat one" }] : []),
      ...corner,
      ...mate(across < 1 - PARALLEL ? "tangent" : "coincident", across < 1 - PARALLEL ? "Mate tangent" : "Mate"),
    ];
  }
  return corner;
}

/** The mate a pair of picks starts as in Mate's panel: two round faces concentric, else coincident. */
export function suggestedMateType(items) {
  const kinds = (items || []).map(item => String(item?.type || item?.pickData?.surfaceType || ""));
  return kinds.length === 2 && kinds.every(kind => kind === "cylinder") ? "concentric" : "coincident";
}
