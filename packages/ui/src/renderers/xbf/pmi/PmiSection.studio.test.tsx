// Studio (studio-base): PMI's switch lighting the faces no tolerance holds (`studioUntolerancedFaces.jsx`).
import React from 'react';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import PmiSection from '../../../../dist/renderers/xbf/pmi/PmiSection.js';
import { useXbfPmi } from '../../../../dist/renderers/xbf/pmi/useXbfPmi.js';
import { readUntolerancedFaces, useUntolerancedFaces } from '../../../../dist/renderers/xbf/pmi/studioUntolerancedFaces.js';
import { presentXbfTree } from '../../../../dist/renderers/xbf/xbfTree.js';

beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// The engine's plate (`pmi_plate/v4`), whose every face holds a tolerance; a test may leave some without.
const FIXTURES = join(dirname(createRequire(import.meta.url).resolve('@cad/core/lib/xbf/xbfDocument.js')), '__fixtures__');
const V4 = JSON.parse(readFileSync(join(FIXTURES, 'pmi_plate', 'v4', 'structure.json'), 'utf8'));
const V4_BOTTOM = 'plate/f:edit_plate.body_make_box1.5;M:edit_plate.body';
const V4_TOP = 'plate/f:edit_plate.body_make_box1.6;M:edit_plate.body';
const PLATE = { min: [-50, -30, -5], max: [50, 30, 5] };
const NOWHERE = () => ({ camera: null, clip: null });

let lit: string[] = [];
function Panel({ structure }: { structure: any }) {
  const scene = React.useMemo(() => ({ structure, elementGeometry: () => null, describeElement: () => null, selectionBounds: () => PLATE }), [structure]);
  const tree = React.useMemo(() => presentXbfTree(structure), [structure]);
  const [selectedKey, select] = React.useState('');
  const pmi = useXbfPmi({ scene, tree, bounds: PLATE, moving: false, editable: true, selectedKey, onSelect: select, here: NOWHERE });
  const untoleranced = useUntolerancedFaces({ structure, tree });
  lit = untoleranced.faceIds;
  return <PmiSection pmi={pmi} picked={[]} moving={false} untoleranced={untoleranced} />;
}
const open = (coverage: unknown) => render(<Panel structure={{ ...structuredClone(V4), pmi_coverage: coverage }} />);
const headings = () => screen.getAllByRole('heading', { level: 2 }).map(heading => heading.textContent);

it('lights the faces no tolerance holds while its switch is on, and says nothing else of coverage', () => {
  open([{ part: 0, uncovered: [V4_BOTTOM, V4_TOP], conflicts: [{ kind: 'unused_datum', ids: ['B'], problem: 'datum B is named by no tolerance' }],
    suggestions: [{ kind: 'material', faces: [], question: 'What is the part made of?', answer: 'material', why: 'a shop quotes it' }] }]);
  expect(headings()).toEqual(['Views', 'Notes', 'Untoleranced faces', 'Annotations']);
  const show = screen.getByRole('checkbox', { name: 'Untoleranced faces' });
  expect(show.getAttribute('aria-checked')).toBe('false');
  expect(lit).toEqual([]);
  fireEvent.click(show);
  expect(show.getAttribute('aria-checked')).toBe('true');
  expect(lit).toEqual(['i0/face/5', 'i0/face/3']);
  fireEvent.click(show);
  expect(lit).toEqual([]);
  // No count, no conflict, no question: the agent asks those in the chat.
  expect(screen.queryByText(/face(s)? ha(s|ve) no/)).toBeNull();
  expect(screen.queryByText(/datum B/)).toBeNull();
  expect(screen.queryByText('What is the part made of?')).toBeNull();
  expect(screen.queryByRole('status')).toBeNull();
});

it('has no switch where every face holds a tolerance', () => {
  // The plate as the engine serves it: every face covered, a question standing.
  render(<Panel structure={structuredClone(V4)} />);
  expect(headings()).toEqual(['Views', 'Notes', 'Annotations']);
  expect(screen.queryByRole('checkbox', { name: 'Untoleranced faces' })).toBeNull();
});

it('reads the served coverage defensively, a part with no untoleranced face left out', () => {
  expect(readUntolerancedFaces(null)).toEqual([]);
  expect(readUntolerancedFaces({ pmi_coverage: 'x' })).toEqual([]);
  expect(readUntolerancedFaces({ pmi_coverage: [{ part: 0, uncovered: [] }, { part: 1, uncovered: [V4_TOP, 4, ''] }, 7, { part: 'a', uncovered: [V4_BOTTOM] }] }))
    .toEqual([{ part: 1, uncovered: [V4_TOP] }, { part: null, uncovered: [V4_BOTTOM] }]);
});
