// Studio's own rules for the ui-strings check (studio-base), read by `check-ui-strings.mjs` so Jake's file
// carries only the lines that use them.

// Studio's CAD mode (Edit by hand): English only for now, as Studio ships in English, so not read.
export const STUDIO_ENGLISH_ONLY = ['packages/ui/src/renderers/xbf/edit/'];

// Studio's lines in Jake's files, English only as its own folder is (`STUDIO_ENGLISH_ONLY`).
export const STUDIO_ALLOWLIST = [
  ['packages/ui/src/renderers/kit/shell/RendererShell.jsx', 'FeatureManager', "Studio's CAD mode's design tree, named as SolidWorks names it"],
];
