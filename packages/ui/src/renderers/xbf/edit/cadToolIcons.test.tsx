import { cleanup, render } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { CadMeasureIcon, CadSelectIcon } from '../../../../dist/renderers/xbf/edit/cadToolIcons.js';
import { measureBadge } from '../../../../dist/renderers/kit/tools/measure/MeasureFilterMenu.js';
import { MEASURE_FILTER_DEFAULT } from '../../../../dist/renderers/kit/tools/measure/measureFilter.js';

afterEach(cleanup);

it("Select's and Measure's buttons in Studio's CAD workspace are its icon generator's, each badge its own", () => {
  // The funnel is the plain icon; Box select, which that set draws no icon for, keeps the kit's.
  const { container: cad } = render(<>{['all', 'parts', 'faces', 'edges', 'position', 'filter'].map(mode => <CadSelectIcon key={mode} mode={mode} />)}
    {[MEASURE_FILTER_DEFAULT, ['vertex'], ['edge'], ['face'], ['vertex', 'face']].map(filter => <CadMeasureIcon key={filter.join()} mode={measureBadge(filter)} />)}
    <CadSelectIcon tool="box" mode="all" /></>);
  expect([...cad.querySelectorAll('use')].map(use => use.getAttribute('href')!.replace('#nx-', ''))).toEqual(['select', 'select-part',
    'select-face', 'select-edge', 'select-position', 'select', 'measure', 'measure-vertex', 'measure-edge', 'measure-face', 'measure']);
  expect([...cad.querySelectorAll('svg[data-tool-icon-base]')].map(icon => icon.getAttribute('data-tool-icon-base'))).toEqual(['boxSelect']);
});
