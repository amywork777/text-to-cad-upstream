// Review facts from the document: allowable limits and relationships.
const clean = value => Number(value.toPrecision(12));
export function dimensionLimits(entry) {
  const d = entry.dimension;
  if (entry.status !== 'ok' || !d || !Number.isFinite(d.nominal) || !d.tolerance
      || !Number.isFinite(d.tolerance.lower) || !Number.isFinite(d.tolerance.upper)) return null;
  return { lower: clean(d.nominal + d.tolerance.lower), upper: clean(d.nominal + d.tolerance.upper), unit: d.unit };
}

export function featureRequirements(entries, ids) {
  const picked = new Set(ids);
  return entries.filter(entry => entry.featureIds.some(id => picked.has(id)));
}

export function datumRelationships(entry, entries) {
  return (entry.tolerance?.datums || []).map((letter, index) => ({
    letter, role: ['Primary', 'Secondary', 'Tertiary'][index],
    entry: entries.find(candidate => candidate.kind === 'datum' && candidate.part === entry.part && candidate.datum?.letter === letter) || null,
  }));
}
