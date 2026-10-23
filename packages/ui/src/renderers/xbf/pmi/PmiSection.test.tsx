import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import PmiSection from '../../../../dist/renderers/xbf/pmi/PmiSection.js';

afterEach(cleanup);
it('opens a selected callout even when a different geometry face remains picked', () => {
  const entry = (id: string, face: string) => ({ id, kind: 'datum', part: 0, status: 'ok', supported: true,
    datum: { letter: id }, glyph: 'datum', callout: { text: `Datum ${id}` }, featureIds: [face], refs: [] });
  const a = entry('A', 'face-a'), b = entry('B', 'face-b');
  const pmi = { entries: [a, b], changes: [], hiddenIds: [], constructions: new Map(), editable: false,
    selectedEntry: b, selectedId: 'B', hover: () => {}, select: () => {}, toggleHidden: () => {} };
  render(<PmiSection pmi={pmi as any} picked={[]} moving={false} selectedFeatureIds={['face-a']} />);
  expect(screen.getByRole('button', { name: 'Datum B', exact: true })).toBeTruthy();
  expect(screen.getByText('Letter')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Datum A', exact: true })).toBeNull();
});
