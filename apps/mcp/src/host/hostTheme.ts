/**
 * The host's colours, font and corner radius on the viewer's own tokens, so the view reads as part of the host's
 * window rather than a frame of its own. MCP Apps hosts send them as standard style variables
 * (`hostContext.styles.variables`: `--color-background-primary`, `--color-text-secondary`...); each one sent is set
 * on the page over `tokens.css`'s value, and one the host stops sending goes back to that value. The viewer's
 * derived surfaces (`--surface-*`, `--background-1`, the CAD workspace's hover) are made from these, so they follow.
 * Sizes and the type scale stay the viewer's: no standard variable carries them.
 */
const HOST_TOKENS: ReadonlyArray<readonly [string, ReadonlyArray<string>]> = [
  ['--color-background-primary', ['--background', '--sidebar']],
  ['--color-background-secondary', ['--card', '--popover']],
  ['--color-background-tertiary', ['--muted', '--secondary', '--accent', '--sidebar-accent']],
  ['--color-text-primary', ['--foreground', '--card-foreground', '--popover-foreground', '--secondary-foreground',
    '--accent-foreground', '--sidebar-foreground', '--sidebar-accent-foreground', '--primary']],
  ['--color-text-inverse', ['--primary-foreground']],
  ['--color-text-secondary', ['--muted-foreground']],
  ['--color-border-primary', ['--border', '--sidebar-border']],
  ['--color-border-secondary', ['--input']],
  ['--color-ring-primary', ['--ring']],
  ['--color-border-danger', ['--destructive']],
  ['--font-sans', ['--font-sans']],
  ['--border-radius-md', ['--radius']],
];

/** The viewer's tokens a host's style variables set: each token by the value the host sent for it. */
export function hostTokens(variables: Readonly<Record<string, unknown>> | undefined): Record<string, string> {
  const tokens: Record<string, string> = {};
  for (const [standard, ours] of HOST_TOKENS) {
    const value = variables?.[standard];
    if (typeof value !== 'string' || !value.trim()) continue;
    for (const token of ours) tokens[token] = value.trim();
  }
  return tokens;
}

/** Every token a host can set, for clearing one it no longer sends. */
export const HOST_SET_TOKENS: ReadonlyArray<string> = [...new Set(HOST_TOKENS.flatMap(([, ours]) => ours))];

/** Sets the host's tokens on `style` (the page's root), clearing the ones it did not send. */
export function applyHostTokens(style: CSSStyleDeclaration, variables: Readonly<Record<string, unknown>> | undefined) {
  const tokens = hostTokens(variables);
  for (const token of HOST_SET_TOKENS) {
    if (token in tokens) style.setProperty(token, tokens[token]!);
    else style.removeProperty(token);
  }
}
