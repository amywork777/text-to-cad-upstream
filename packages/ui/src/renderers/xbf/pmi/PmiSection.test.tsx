import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import PmiSection from '../../../../dist/renderers/xbf/pmi/PmiSection.js';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const section = (overrides: Record<string, unknown>) => ({ changes: [], pending: [], hiddenKeys: [], constructions: new Map(), editable: false,
  selectedEntry: null, selectedKey: '', hover: () => {}, select: () => {}, toggleHidden: () => {}, edit: () => {}, focusDatum: () => {}, ...overrides });
const datum = (part: number, letter: string, face: string) => ({ key: `${part}:${letter}`, id: letter, kind: 'datum', part, status: 'ok', supported: true, warnings: [],
  datum: { letter }, glyph: 'datum', callout: { text: `Datum ${letter}` }, featureIds: [face], refs: [] });
const position = (part: number, datums: string[], face: string) => ({ key: `${part}:hole-pos`, id: 'hole-pos', kind: 'geometric_tolerance', part, status: 'ok', warnings: [],
  supported: true, glyph: 'position', tolerance: { characteristic: 'position', value: 0.1, unit: 'mm', zone: 'diameter', datums },
  callout: { text: `Position ⌀0.1 | ${datums.join(' | ')}`, title: 'Position', diameter: true, value: '0.1' }, featureIds: [face], refs: [] });

it('opens a selected callout even when a different geometry face remains picked', () => {
  const a = datum(0, 'A', 'face-a'), b = datum(0, 'B', 'face-b');
  render(<PmiSection pmi={section({ entries: [a, b], selectedEntry: b, selectedKey: b.key }) as any} picked={[]} moving={false} selectedFeatureIds={['face-a']} />);
  expect(screen.getByRole('button', { name: 'Datum B', exact: true })).toBeTruthy();
  expect(screen.getByText('Letter')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Datum A', exact: true })).toBeNull();
});

it('lists two parts\' datum A apart, and a position offers its own part\'s datums alone', () => {
  const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
  const pegs = position(1, ['B'], 'i1/face/2');
  const entries = [datum(0, 'A', 'i0/face/5'), datum(1, 'A', 'i1/face/1'), datum(1, 'B', 'i1/face/3'), pegs];
  render(<PmiSection pmi={section({ entries }) as any} picked={[]} moving={false} />);
  expect(screen.getAllByRole('button', { name: 'Datum A', exact: true })).toHaveLength(2);
  cleanup();
  render(<PmiSection pmi={section({ entries, editable: true, selectedEntry: pegs, selectedKey: pegs.key }) as any} picked={[]} moving={false} />);
  expect([...document.querySelectorAll('[data-pmi-datum-choice]')].map(choice => choice.getAttribute('data-pmi-datum-choice'))).toEqual(['A', 'B']);
  expect(errors.mock.calls.flat().join(' ')).not.toMatch(/same key/);
});

it('picks a related annotation from a datum\'s values with the whole list shown', () => {
  const a = datum(0, 'A', 'face-a'), uses = position(0, ['A'], 'face-b');
  function Harness() {
    const [key, setKey] = React.useState(a.key);
    const entries = [a, uses];
    return <PmiSection pmi={section({ entries, selectedKey: key, selectedEntry: entries.find(entry => entry.key === key), select: setKey }) as any}
      picked={[]} moving={false} />;
  }
  render(<Harness />);
  // The datum picked: the list follows its face, and its values say what uses it.
  expect(screen.queryByRole('button', { name: 'Position ⌀0.1 | A', exact: true })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Position ⌀0.1 | A', exact: true }));
  expect(screen.getByRole('button', { name: 'Position ⌀0.1 | A', exact: true }).getAttribute('aria-pressed')).toBe('true');
  expect(screen.getByRole('button', { name: 'Datum A', exact: true })).toBeTruthy();
});

const basicFromLeft = (overrides: Record<string, unknown> = {}) => ({ key: '0:hole-from-left', id: 'hole-from-left', kind: 'dimension', part: 0, status: 'ok',
  supported: true, glyph: 'dimension', statusText: '', warnings: [], featureIds: ['i0/face/9'], refs: [], callout: { text: '44 basic' },
  dimension: { type: 'distance', basic: true, nominal: 44, unit: 'mm', source: 'geometry', tolerance: null }, ...overrides });

it('says what the build warned of on an annotation, on its row and in its values', () => {
  const warned = 'f:cut.1 named a cylinder face on the last build and names a plane face now: another face than the annotation was made on, measured as it is.';
  const entry = basicFromLeft({ warnings: [warned] });
  render(<PmiSection pmi={section({ entries: [entry], selectedEntry: entry, selectedKey: entry.key }) as any} picked={[]} moving={false} />);
  expect(screen.getByRole('button', { name: `44 basic: ${warned}`, exact: true })).toBeTruthy();
  expect(screen.getByRole('status').textContent).toBe(warned);
  cleanup();
  // None warned of: nothing said.
  const quiet = basicFromLeft();
  render(<PmiSection pmi={section({ entries: [quiet], selectedEntry: quiet, selectedKey: quiet.key }) as any} picked={[]} moving={false} />);
  expect(screen.getByRole('button', { name: '44 basic', exact: true })).toBeTruthy();
  expect(screen.queryByRole('status')).toBeNull();
});

it('says a nominal another system\'s file gives as the file\'s, and one the engine measured as measured', () => {
  const measured = basicFromLeft();
  render(<PmiSection pmi={section({ entries: [measured], selectedEntry: measured, selectedKey: measured.key }) as any} picked={[]} moving={false} />);
  expect(screen.getByText(', measured')).toBeTruthy();
  cleanup();
  const given = basicFromLeft({ dimension: { ...basicFromLeft().dimension, source: 'file' } });
  render(<PmiSection pmi={section({ entries: [given], selectedEntry: given, selectedKey: given.key }) as any} picked={[]} moving={false} />);
  expect(screen.getByText(', from the file')).toBeTruthy();
  expect(screen.queryByText(', measured')).toBeNull();
  expect(document.querySelector('[title="Measured on the geometry by the engine"]')).toBeNull();
});
