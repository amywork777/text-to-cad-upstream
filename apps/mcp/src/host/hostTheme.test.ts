import { describe, expect, it } from 'vitest';
import { applyHostTokens, hostTokens } from './hostTheme';

describe("the host's theme", () => {
  it("puts the host's standard style variables on the viewer's tokens", () => {
    const tokens = hostTokens({ '--color-background-primary': 'oklch(0.14 0 0)', '--color-text-secondary': ' #888 ',
      '--border-radius-md': '0.5rem', '--color-unknown': 'red', '--color-border-primary': '' });
    expect(tokens['--background']).toBe('oklch(0.14 0 0)');
    expect(tokens['--sidebar']).toBe('oklch(0.14 0 0)');
    expect(tokens['--muted-foreground']).toBe('#888');
    expect(tokens['--radius']).toBe('0.5rem');
    // Nothing sent, or sent empty, leaves the viewer's own.
    expect('--border' in tokens).toBe(false);
    expect(hostTokens(undefined)).toEqual({});
  });

  it('clears a token the host stopped sending', () => {
    const style = document.createElement('div').style;
    applyHostTokens(style, { '--color-background-primary': 'black', '--color-border-primary': 'grey' });
    expect(style.getPropertyValue('--border')).toBe('grey');
    applyHostTokens(style, { '--color-background-primary': 'black' });
    expect(style.getPropertyValue('--border')).toBe('');
    expect(style.getPropertyValue('--background')).toBe('black');
  });
});
