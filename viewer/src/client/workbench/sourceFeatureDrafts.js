const AXIS_NAMES = ["x", "y", "z"];

export function sourceFeatureType(feature) {
  const op = String(feature?.op || "");
  if (op === "extrude") return feature?.mode === "subtract" ? "Cut-Extrude" : "Boss-Extrude";
  if (op === "revolve") return feature?.mode === "subtract" ? "Cut-Revolve" : "Revolve";
  if (["Box", "Cylinder", "Sphere"].includes(op)) return "Boss-Extrude";
  if (op === "fillet") return "Fillet";
  if (op === "chamfer") return "Chamfer";
  return op || "Feature";
}

export function decorateSourceFeatures(features) {
  const counts = new Map();
  let sketchCount = 0;
  return (Array.isArray(features) ? features : []).map((feature) => {
    const type = sourceFeatureType(feature);
    const count = (counts.get(type) || 0) + 1;
    counts.set(type, count);
    const sketch = feature?.sketch
      ? { ...feature.sketch, label: `Sketch${++sketchCount}` }
      : null;
    return { ...feature, type, label: `${type}${count}`, sketch };
  });
}

export function sourceParamKey(parameter) {
  const span = Array.isArray(parameter?.span) ? parameter.span : [];
  return span.length === 2 ? `${span[0]}:${span[1]}` : "";
}

export function featureParameterRows(feature, selectedNodeId) {
  if (!feature) return [];
  if (feature.sketch?.id === selectedNodeId) {
    return (Array.isArray(feature.sketch.entities) ? feature.sketch.entities : []).flatMap((entity, entityIndex) => {
      const group = `${entity.op}${entityIndex + 1}`;
      return [
        ...(Array.isArray(entity.params) ? entity.params : []),
        ...(Array.isArray(entity.positionParams) ? entity.positionParams : []).map((parameter) => ({
          ...parameter,
          name: `center_${parameter.name}`,
        })),
      ].map((param) => ({ ...param, group }));
    });
  }
  const rows = [...(Array.isArray(feature.params) ? feature.params : [])];
  const values = Array.isArray(feature.position?.value) ? feature.position.value : [];
  const spans = Array.isArray(feature.position?.elementSpans) ? feature.position.elementSpans : [];
  spans.forEach((span, index) => {
    rows.push({ name: AXIS_NAMES[index] || `axis${index + 1}`, value: values[index], span, group: "Position" });
  });
  return rows;
}

export function buildSourceEdits(source, drafts) {
  const text = String(source || "");
  return Object.values(drafts || {})
    .filter((draft) => Array.isArray(draft?.span) && draft.span.length === 2)
    .map((draft) => ({
      start: draft.span[0],
      end: draft.span[1],
      expected: text.slice(draft.span[0], draft.span[1]),
      replacement: String(draft.value),
    }))
    .sort((a, b) => a.start - b.start);
}

export function sourceDraftsValid(drafts) {
  return Object.values(drafts || {}).every((draft) => {
    const text = String(draft?.value ?? "").trim();
    return text !== "" && Number.isFinite(Number(text));
  });
}
