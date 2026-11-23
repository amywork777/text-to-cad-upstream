import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { withStripPanelToggle } from '../../../../dist/renderers/kit/shell/stripPanelToggle.js';

afterEach(cleanup);

const display = { id: 'display', label: 'Display', icon: null, tile: <button type="button">Display</button> };

// Studio (studio-base): a view the file viewer draws with no navbar (`chrome: "bare"`) leads its strip's view
// controls with the panel's toggle, the navbar's first control; under a navbar, or outside a file viewer, it does not.
it('leads the strip with the panel\'s toggle only where no navbar holds it, as the navbar\'s toggle: its name, key and state', () => {
  const toggle = vi.fn();
  const toggles = { left: { open: false, label: 'Show panel', shortcut: '⌘\\', toggle } };
  expect(withStripPanelToggle([display], toggles, true)).toEqual([display]);
  expect(withStripPanelToggle([display], toggles, null)).toEqual([display]);
  // No panel (edit mode's design tree stands in for it): no toggle.
  expect(withStripPanelToggle([display], null, false)).toEqual([display]);
  const views = withStripPanelToggle([display], toggles, false);
  expect(views.map((view: { id: string }) => view.id)).toEqual(['panel', 'display']);
  expect([views[0].label, views[0].onSelect]).toEqual(['Show panel', toggle]);
  render(<>{views[0].tile}</>);
  const button = screen.getByRole('button', { name: 'Show panel' });
  expect([button.getAttribute('aria-expanded'), button.getAttribute('aria-keyshortcuts'), button.hasAttribute('data-strip-panel')]).toEqual(['false', '⌘\\', true]);
  fireEvent.click(button);
  expect(toggle).toHaveBeenCalledTimes(1);
});
