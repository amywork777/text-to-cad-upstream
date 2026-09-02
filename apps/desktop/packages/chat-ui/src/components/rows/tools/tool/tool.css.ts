import { style } from '@vanilla-extract/css';
import { textShimmer } from '@styles/effects.css';
import { sx } from '@styles/sprinkles.css';
import { vars } from '@styles/theme.css';
import { createVariableThemeContract } from '@styles/variable-theme-contract.css';

// ── Runtime geometry contract ─────────────────────────────────────────────────

export type ToolStyleVars = { rowH: number };

export const toolVars = createVariableThemeContract<ToolStyleVars>({ rowH: null });

export const toolRoot = style([
  sx({ display: 'flex', alignItems: 'center', borderColor: 'border' }),
  // overflow:hidden ensures content never escapes the reserved rowH.
  { height: toolVars.rowH, overflow: 'hidden' },
]);

export const toolRow = style([
  sx({ display: 'flex', alignItems: 'center', gap: '1.5', color: 'fgPassive', userSelect: 'none' }),
  // min-width:0 lets flex children shrink below their intrinsic width so
  // text-overflow ellipsis can take effect on the name and summary spans.
  { minWidth: 0 },
]);

export const toolName = style({
  fontSize: vars.typeBodyFontSize,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  flexShrink: 1,
  maxWidth: '100%',
  minWidth: 0,
});

export const toolNameWithSummary = style({
  maxWidth: '55%',
  flexShrink: 0,
});

export const toolSummary = style([
  toolName,
  {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    opacity: 0.75,
    flexShrink: 1,
    maxWidth: 'none',
  },
]);

export const toolStatus = style({
  position: 'absolute',
  width: '1px',
  height: '1px',
  padding: 0,
  margin: '-1px',
  overflow: 'hidden',
  clip: 'rect(0, 0, 0, 0)',
  whiteSpace: 'nowrap',
  borderWidth: 0,
});

export const toolStatusIcon = style({
  marginLeft: 'auto',
  display: 'inline-flex',
  flexShrink: 0,
});

export const toolPermissionIcon = style([
  toolStatusIcon,
  {
    color: '#eab308',
  },
]);

export const toolErrorIcon = style([
  toolStatusIcon,
  {
    color: vars.fgError,
  },
]);

export { textShimmer };
