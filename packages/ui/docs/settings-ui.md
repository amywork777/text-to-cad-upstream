# Viewer interaction and settings design system

This is the binding contract for the viewer's tools, its file sidebar and its
settings, in both apps. Build from the shared pieces — the
[toolbar button](../src/primitives/toolbar-button.jsx),
[FloatingToolBar](../src/renderers/kit/tools/FloatingToolBar.js),
[SubToolbar](../src/renderers/kit/tools/SubToolbar.jsx),
[ToolPopover](../src/renderers/kit/tools/ToolPopover.jsx),
[FileSidebar](../src/renderers/kit/tools/FileSidebar.jsx),
[ToolStack](../src/renderers/kit/tools/ToolStack.jsx),
[ToolPanel](../src/renderers/kit/tools/ToolPanel.jsx),
[the floating surface](../src/lib/floatingSurface.js) and the
[FileSheet primitives](../src/renderers/kit/inspector/FileSheet.js) — and extend
them rather than recreating their layout in a renderer. Environmental effects
belong to apps through the [host contract](viewer-host.md).

## Ownership and layout

FileViewer owns the navbar — the logo's app menu ([Settings](#settings)) included, built from
the host's `links` and the `appSettings` `CadViewer` hands it — and the file explorer (a
popover under the file's name). RendererShell owns the scene's chrome: the tool strip and
the view's controls at its end (Display, Preview), the sub-toolbar of the tool in hand under
it, the file sidebar, Quick Edit, the view cube and Preview. Renderers supply
their tools, their tools' rows, their sidebar sections and their document state; the shell never
inspects a format's parts, joints or topology. No pick or tool opens or closes the explorer.

| The host (web, desktop) supplies | The shared UI decides |
| --- | --- |
| Where the tab record lives (`TabRecordStorage`: the web's sessionStorage, the CAD app's memory) | The record: its settings (the file sidebar's and tool stack's layout, the appearance, the home's layout) and the view of the file on screen (its camera, Display settings, its playback settings, and renderer slices), what is written when, and what is never stored (`@text-to-cad/ui/tab-store`, `kit/shell/fileView.js`) |
| `navigation.home`, `links` (its version, GitHub, Discord, where a new issue opens, how a link opens), `appSettings` (the person's own settings), `colorScheme` (the person's theme and how it changes) and `colorSchemeControl` (the home's light/dark button, where it has one) | The navbar's order and look, the app menu (one menu in the viewer and on the home) and what a new issue says |
| `host.files`, `fileActions`, `navigation`, `clipboard`, `promptContext`, `promptFiles` | When a copy, capture or open happens and what it carries |
| `host.environment`: color scheme, keyboard `platform`, `reducedMotion` | How the chrome honours them |
| `onError`, for errors the viewer hands up | Preview, tooltips, keyboard scope, the tool strip and sidebar, the camera |

Hosts pass no Preview, chrome-visibility or notification props; there are
none.

- **Navbar.** One row, the same in every app, over every file. Left: the text-to-cad "C"
  logo, named Menu, the size of the row's icon buttons, with no chevron, which opens the
  **app menu** (see [Settings](#settings)) — a host with no home has it too — then, where the
  host keeps the view's own history (`history`: the CAD app's views, which no browser holds),
  **Back** and **Forward**, two arrows walking it as a browser's do, from file to file (the home
  is no step: it is a way to pick a recent file), each there always and disabled where it has
  nowhere to go; then the open file's name and its ⋯. Each of these that
  is a control (`NAV_ITEM_CLASS`) is transparent at rest, takes the same accent background
  while the pointer is on it and while its menu is open, has a pointer cursor and no tooltip:
  it says what it is. The name
  is that control where it opens the explorer (below), where the host's files can be
  browsed; where they cannot it is plain text. The ⋯
  is the file menu: Copy path, and Reveal in Finder / Show in Explorer / Show in file
  manager, each only where the host can do it, and no ⋯ where it can do none. The name has
  no right-click menu and there are no crumbs. The left's controls sit edge to edge, spaced
  by their own padding alone: the logo's 24px button, Back, Forward and the ⋯ in 20px ones,
  and the name 4px in from its edges, so about 7px separate one glyph from the next. Right, only what a host or a file adds: first, the
  update — a blue download button, there only when the host
  found a newer release, whose menu says the step to it, how this host updates and what
  is new. Then, while a person has put an alert card away: the card's own icon (a circle
  with an exclamation mark, red for an error and amber for a warning, named and hinted by
  the alert's title), which brings the card back and goes with it — the renderer's one
  navbar action. Then, where the host shows the view small (inline in a conversation,
  where the view is the whole viewer), its **Full size**, corner brackets. A CAD file publishes no navbar action but that
  icon. The person's own settings, the theme among them, are never here: they are the app
  menu's.

  *Design note: the strip is for tools; the view's controls are the navbar's.* What a host or
  the file adds (the update, an alert's icon, Full size) is the navbar's right end, and last
  after them the view's own controls, **Display** and **Preview** (`navbarSlot`): they act on
  the whole view, whatever tool is in hand, so they are no tools. In Preview the same place
  holds its own controls, **Preview settings** and **Exit preview**. A host with no navbar has
  them over the view instead: Display and Preview ending the strip after a thin rule, the
  Preview's pair in the view's top-right corner. A new per-file button that is no tool goes
  with them.

  A host's home has no navbar: under its TEXTTOCAD wordmark and byline, its update, when there is
  one, is a row of its own (the blue button, labeled **Update**, its card centred under it), then
  GitHub (its mark, a link to the project: it is open source), Discord and X, as icon links, and,
  where the host shows the view small, **Full size**, then the host's colour scheme control,
  where it has one, last in that row, above its Recent Files: the models opened before,
  pinned first, as cards or rows, with Open where the host has a file chooser.
  The update shows only for a release
  later than the version the page names, whatever the host says. A file that will not open
  shows a page under the navbar: "File does not exist" and the file's path, or "Could not
  open that file" and the reason, each with **Go home** where the host has a home. A view
  drawn as a picture (`compact`, the home's thumbnails) has no navbar either, and draws the
  model alone: no tools, view actions, cube or Quick Edit.
- **File explorer** is a popover under the file's name (`FolderExplorer.jsx`), aligned to
  the name's left edge, 18rem wide and never resized, as tall as its rows up to 28rem or
  the room below it: past that its list scrolls. It floats over the view and the file
  sidebar, so opening it resizes and moves nothing. It starts in the open file's folder and
  lists one folder at a time — its subfolders, then its CAD files — in compact rows: one 24px
  line of 12px text each, its kind a small light glyph in one column 5px in from the row's
  left end and 4px before the name (a folder its disclosure chevron, with no folder icon; a
  file its type's icon), as the file sidebar's trees draw theirs. A press on a subfolder opens it
  inline, under itself, its rows 10px further in and hung from a faint line under its
  chevron, read once when it first opens; another press closes it, and Right and Left do the
  same from the keyboard. A double-click opens it in the explorer's place, as a crumb does —
  the breadcrumb then names it. The breadcrumb is
  as many of the last three folders as fit whole: every crumb is its folder's whole name, the
  farthest giving way first to the "…" (an ellipsis icon), which lists every folder above the crumbs to jump to,
  and only the folder it is in, left alone beside the "…", is cut (its name a hint while it
  is). The folder it is in reads in the foreground color, the others muted; there is no up
  arrow, and the open file is highlighted, the list opening scrolled to centre its row, once (a
  long folder's too). Opened, its filter has the keyboard, so typing
  finds a file at once; on a phone the explorer itself holds focus, keeping the keyboard
  down. "Filter files..." under the breadcrumb searches
  every file nested under the folder (the server's bounded search, debounced 150ms, each
  keystroke cancelling the search before it); a search that stopped early says "Stopped
  early. Keep typing to narrow the search." Up and Down move between the filter and the
  rows on screen, the rows of a folder open inline among them. A pick opens the file and
  closes it, as do Escape and a press anywhere outside it.
- **Tool strip** at the top centre, 8px down, never wider than the view less 8px at each
  side (it wraps before it would be): the tools, left to right (with no navbar, then a thin
  rule and the view's controls, **Display** and **Preview**: below). 24px tiles with 14px icons,
  an even 4px apart, a tool's chevron touching its button, in a 34px row (`FloatingToolBar`,
  `data-cad-toolbar`). A file with no tools has no strip. On a phone
  ([mobile](#the-file-sidebar-and-the-tool-stack)) the tiles are 36px with 18px icons, a chevron
  20px wide, in one row that never wraps. Centre it on the viewport whenever it fits;
  clamp its position to keep 8px from the edges and from the file sidebar's tile at its left.
  Its available width still uses all the room after that tile. What does not fit goes, from the
  strip's end (the view's controls where the strip has them, then the tools from the last), into **More tools** (an ellipsis, last), a tool a row ticked while it is
  in hand and Display opening its popover from More (`touchStripFit`).
- **Sub-toolbar** under the strip, 8px below it, centred: the tool in hand's one row of
  controls (`SubToolbar`, `data-cad-sub-toolbar`), there for as long as the tool is up (see
  [Tools and lifecycle](#tools-and-lifecycle)). Select and Measure have none. On a phone its
  buttons are the strip's 36px tiles and its sliders as tall, the slider rows 20rem wide.
- **Tool stack** under the sub-toolbar, in the same centred column: a renderer's own
  `toolPanels`, where it hands any (see
  [The file sidebar and the tool stack](#the-file-sidebar-and-the-tool-stack)). The column
  stops 8px above the cube's line (`VIEWPORT_STACK_BOTTOM`), so it never runs past the
  view.
- **File sidebar** at the top-left, 8px in: a toolbar of tiles, one per section of what there
  is to read of the file — a STEP assembly's Model tree, a robot's Links, Position, an SDF's
  metadata, the routines' Animation — whatever tool is in hand; a tile opens its section in a
  panel under the tiles, one at a time, down to 8px off the view's bottom at most. On a phone it
  is one tile, opening one panel with the sections as tabs (see
  [The file sidebar and the tool stack](#the-file-sidebar-and-the-tool-stack)).
- **Quick Edit** at top-right, 8px in, a STEP's or a robot's: the box of the note a
  person writes to their agent, there only while something is picked, drawn or measured
  (see [Quick Edit](#quick-edit)). The rest of the right side of the view is clear.
- **View cube** at bottom-right, 2px from the right and 8px off the bottom so the axes
  drawn in its lower corner never touch the edge (`VIEWPORT_CUBE_BOTTOM`), in a 6rem area:
  enlarged face/edge/corner hit areas and neutral hover and XYZ guides. A host whose own
  control floats over that corner lifts it clear with `--cad-viewport-corner-bottom`, the
  room that control takes from the bottom edge. A host can instead anchor it at bottom-left
  with `--cad-viewport-corner-left: 2px` and `--cad-viewport-corner-right: auto`.
  Codex's tab presentation uses this for all its views to avoid the floating composer.
  Preview omits it, and so does a phone.
- **Display and Preview** end the navbar, for a 3D file (`data-view-controls`, the box
  FileViewer hands the renderer as `navbarSlot`): **Display** (the active mode's sphere: see
  [Display settings](#display-settings-and-section-primitives)) and **Preview** (a play
  triangle, the way into Preview), the navbar's icon buttons, hinted below them. They are no
  tools: pressing one leaves the tool in hand as it is. Display's dropdown opens down from its
  button, aligned to its end, never taller than the viewer below it. A view that is not 3D has
  none of them, and neither does a view drawn as a picture or one that is loading or failed to
  load; in Preview the same place holds its own controls (see
  [Preview](#camera-animation-and-preview)). With no navbar (a host showing the view
  alone) they end the tool strip after its rule, and Preview's stand in the view's top-right
  corner.
- **Nothing sits at the bottom centre**, in the tools view or Preview: a file's routines
  play from the file sidebar's Animation section (see [Preview](#camera-animation-and-preview)).
- **Model update status** sits under the strip and its sub-toolbar, centred, and where
  there is no strip (Preview, a compact view, a load) at the top centre, in the strip's
  34px row, in every host. It is renderer chrome: the navbar carries no status. On mobile
  it is a tappable progress icon whose popover names what is loading.

## Tools and lifecycle

| File | Tool strip, left to right |
| --- | --- |
| STEP | Select, Annotate, Measure, Explode (two or more parts), Clip; then Display and Preview |
| URDF / SRDF / SDF | Select, Annotate, Measure, Clip; then Display and Preview |
| GLB | Select, Annotate, Measure, Explode (several rigid nodes that draw), Clip; then Display and Preview |
| 3MF | Select, Annotate, Measure, Clip; then Display and Preview |
| STL | Select (in hand, the view's navigation: an STL picks nothing), Annotate, Clip; then Display and Preview |
| DXF | Select (in hand, and the view's hand: a drag pans, a tap picks an entity), Annotate, Measure; no view controls: a drawing is 2D |

There is no activity dot. A thin rule parts the tools from the view's controls, which
are no tools (see [Ownership and layout](#ownership-and-layout)). Position is no tool:
its knobs are Select's, while Select's filter picks Position, and its controls are a
section of the [file sidebar](#the-file-sidebar-and-the-tool-stack), and so is Animation, where
the file's routines play (see [Preview](#camera-animation-and-preview)). A file with no tools
and no 3D view has no strip at all.

**A tool the file cannot offer is not on the strip**: never shown disabled.
Renderers leave it out of the `tools` they hand over; `FloatingToolBar` draws
what it is given. Until a file has loaded, what it offers is not known: a tool
that depends on it (Explode) is shown idle meanwhile, a robot's filter offers
Position meanwhile, and the whole strip is disabled while loading. Unavailable and
idle are different states.

One tool owns pointer input, and it alone is lit on the strip. An effect a person set —
an explosion, a cut, a pose — stays on the model once its tool
is put down, with nothing on screen for it but the model. **A press on the tool in hand
does nothing**: a tool is put down by taking up another (Select, most often), or by Escape, which
takes Select up. A press on
Explode or Clip with its effect set takes it up again, as it is; unset, it starts neutral.

| Tool | Pressing it | Its sub-toolbar | Leaving it |
| --- | --- | --- | --- |
| Select | The default tool of every 3D file but an STL; picks what its filter ticks, or a GLB's nodes, a 3MF's objects (Shift adds; Delete deletes annotations and measurements); what is picked is Quick Edit's chips | None: its filter is the chevron after its button | The selection stays, lit and in Quick Edit, under any tool |
| Annotate | Draws on the view | Its tools, what is drawn next, Undo, Redo and Clear annotations (on a phone, the menu of a chevron after its tile instead) | The annotations stay in the model, their chip in Quick Edit; the tool in hand stays, the strip's Annotate showing its icon |
| Measure | Arms picking between points on the model (a STEP's exact vertices, edges and faces; a mesh's triangles, approximately, in its file's unit; a drawing's ends, centres and lines, in the unit it declares, else "units"); each result a chip in Quick Edit, in its colour | None | Unfinished picks are cancelled; completed measurements stay, Quick Edit's chips |
| Explode / Clip | The effect as it is set, or neutral; an edit applies it (Explode's, as a motion: see below) | The slider, its amount beside it, Reset (Clip's: its axis first, and Flip clip before Reset) | The effect stays on the model |

**One motion at a time.** Every tool's state stands beside every other's — the selection,
measurements, the annotations, Clip — except the two that move the parts: **Explode** and
the **Position** pose. They replace each other: taking up Explode puts the pose back at its
default, and using Position (a knob dragged, a value set or a named pose chosen) takes
Explode off, with nothing set aside to come back. While the model is exploded there are no
knobs. Put down, Explode keeps its explosion under any other tool until Position is used. A
routine played from the Animation section is the third motion: playing it puts Explode and the
pose back at rest, and using either puts the routine back at rest; paused, its frame stays on the
model as a pose does. Preview's routine is its own and moves nothing of the tools view's.
Another file has the motions its tools have, under the same rule, decided by value
(`kit/tools/model-effects/motionExclusion.js`): a GLB's Explode, routine and Clip; a robot's
Position and Clip.

A tree is the file sidebar's, on screen under every tool; a pick in it takes Select up
before it acts.

**Removing an effect.** Explode's and Clip's sub-toolbars end in
Reset ("Reset explode", "Reset clip"): always there, disabled while there
is nothing to take away, it removes the effect and leaves the tool up. Position's way back is its Pose row's Default. A
measurement's chip X deletes it; the Annotation chip's X clears the annotations.

**Select is the one tool with a menu on the strip**: the chevron right after its button
(`ToolSettingsMenu`'s "chevron" trigger, `kit/tools/ToolModeMenu.jsx`), a small button of
its own as tall as the tile and touching it, lit by its own hover and while its menu is
open, never with the tool. A press on any other tool is its only action. Whatever a tool can
be set to while it is up is its sub-toolbar. A dropdown is ordinary — under its own button,
free to overlap the view — and closes with no exit animation, so a quick second tap (touch
included) always reaches its trigger. Choosing a value closes it; ticking an option leaves
it open. Menu checks sit on the right. The other dropdowns over the viewport are Display,
the sub-toolbars' (Clip's axis, Annotate's colour, weight, line style and placement), its
context menu, and the Animation section's routine and Playback settings (`PlaybackMenu.jsx`, on
`ToolPopover`). Preview's settings are a panel, not a dropdown (see [Preview](#camera-animation-and-preview)).

**Select's filter** (`kit/tools/select/SelectFilterMenu.jsx`), as a CAD tool's selection
filter is: the chevron's dropdown, headed "Selection filter", then **Select all** — ticked
when every kind is, a dash (indeterminate) when some are; pressing it ticks every kind, or,
with every kind ticked, none — then, after a rule, a checkbox per kind of thing Select picks,
each with its glyph and each on its own. A STEP's (`SelectionModes.jsx`): **Parts** (a whole
cube; an assembly's only — a part file's filter offers none, and a press that reaches no face
or edge picks the whole part), **Faces** (a faint cube, its top face filled), **Edges** (a
faint cube, one edge heavy), **Position** (where the file has joints to move: its knobs),
**Annotations** and **Measurement**. A robot's: **Links** and **Position** (where a
joint can be driven). Every kind is ticked when a file opens; the filter holds while the file
is open, across updates of it, and another file starts with every kind. Ticking leaves the
menu open, so several change in one go, and takes Select up. The chevron's name says what is
picked ("Selection filter: everything", "Selection filter: Faces, Edges", "…: nothing").
Select's button is the pointer, whatever the filter. After another rule, a STEP's filter ends
in how a face or edge pick grows, each with its glyph and independent of the filter and of
each other: **Group edges** (the connected edges with a picked edge), shown while Edges is
ticked, and **Group faces** (the smoothly joined faces with a picked face), shown while Faces
is; a hidden one keeps its choice for when it shows again.

The geometry ticked is picked as one mode (`step/workbench/selectionFilter.js`'s
`selectGeometryMode`): Parts with Faces or Edges, a press takes the face or edge it lands on
where the part's topology can be picked, and the part elsewhere; Parts alone, the part;
Faces or Edges without Parts, that topology alone. The mode sets the model tree's shape:
with Parts and Faces or Edges, or no geometry at all, it is the person's own (put back as it
was when they left it, with the owners of what is still selected kept open); Parts alone
opens every assembly and shuts every part; Faces or Edges without Parts open every assembly. A
part is a leaf in every shape: nothing opens under it, and a face or edge picked in the
viewport is revealed at its part's row. Outside the person's own shape the disclosure is
locked (chevrons shown, not pressable) and Expand/Collapse leave the row menus. Under Faces
or Edges a part's topology is asked for as its row comes on screen in the tree, never for a
whole large assembly at once; a viewport press on a part not yet loaded loads that part and
picks, and the model tree's heading says "Loading…" meanwhile. In a large assembly (more than 300
rows of assemblies and parts, `LARGE_TREE_ROWS`) a part's row coming on screen asks for
nothing: the pointer resting on the part in the viewport (150ms) or pressing it asks.

**Sub-toolbars** (`kit/tools/SubToolbar.jsx`): the tool in hand's controls, one row hung
under the strip, centred, 8px below it, on the strip's surface, its buttons the strip's
24px tiles, its groups — what the tool does, how it looks, what it can undo — parted by a
thin rule. It stays up for as long as its tool does, and has no heading: the tool's lit
button above names it. Explode's and Clip's are one shape — what leads
the slider, the slider, its value right beside it and only as wide as
its text, the tool's actions, then Reset, last, at the same spot in both, with no rules —
and one width (`SLIDER_SUB_TOOLBAR_CLASS`, `w-56`). The slider takes the rest of the row.

**Annotate.** Its sub-toolbar, "Annotation controls", while Annotate is up
(`annotation/toolbar.jsx`'s `AnnotationToolbar`): **Annotation tools**, a button each — Pen,
Line, Arrow, Rectangle, Ellipse, Text (a mark put down in place) and Eraser — then a rule and
**Annotation style**, what is drawn next, each a dropdown whose button shows its value, no
chevron: **Color** (a grid of swatches, unnamed but for assistive technology: the neons and
one neutral that reads against the viewer, white in dark mode and near-black in light, then
the colour wheel, which opens the system's colour picker for any other colour, kept once the
picker closes), **Stroke width** (Thin, Medium, Bold — a shape's 1, 2 or 4px, the pen drawn to
look the same weight, its glyph a dot 3, 5 or 7px across) and **Line style** (Solid, Dashed,
Dotted — a shape's line; the pen's freehand ink is always solid; its glyph a diagonal line
drawn in the style), each a row of glyphs alone, the current one marked, and **Placement**
(**Draw on surface**, the default, its glyph a sphere: ink carried with the part under it;
**Draw on plane**, on a plane facing the view through the orbit point, on no part, its glyph a
plane), its glyphs with their names; then **Annotation history** — **Undo**, **Redo** — and
**Clear annotations** (the trash), each disabled while there is nothing for it, with no rule
before them. In a view narrower than 32rem the seven tools and the seven after them are two
rows, column for column, with no rule. Annotate has no Select or Pan of its own (Select picks
annotations, a right drag or Space orbits). Never a restyle of ink already down: the
annotations Select picks have their own bar, a small floating toolbar on the tool strip's
surface just above them — Color, Stroke width and Line style dropdowns, Fill for a closed
shape, a rule, Delete. An update of the model forgets the annotations too, their history with
them (Undo has nothing to bring back), and leaves Annotate the tool, on the tool, colour,
weight, line style and placement in hand. The pen and the shapes share one default stroke
width. The annotations have no panel: while there are any they are Quick Edit's
**Annotation** chip (its X clears them), and while Annotate is up the copy shortcut writes
the view with its annotations to the clipboard as a PNG. A first stroke opens
[Quick Edit](#quick-edit), whose header says **annotation** while there is ink. Annotate
disables the cube without hiding it.

**Measure.** It has no sub-toolbar and no menu: it measures between points on the model,
snapping to no edge or face, and its button is the ruler. Each completed measurement
is a chip in [Quick Edit](#quick-edit): the ruler in the measurement's own colour (the
colour of its line on the model) and its reading; its X deletes it, resting on it lights
its line and labels it, and its card is the full reading (the distance, the angle where
there is one, the delta along each axis, what each end bound to). Measurements stay under
every other tool; a press on Measure while it is up does nothing.

**Explode and Clip** have no enabled checkbox, and their sub-toolbars are drawn alike.
Explode's: its slider, the amount (a percentage), **Reset explode**. Clip's: its axis — a
borderless button reading the axis in hand, "X ⌄", whose dropdown lists X, Y and Z — its
slider, the amount, **Flip clip** (which side of the plane is cut away, the cut keeping its
share; disabled while nothing is cut), **Reset clip**. Explode opens at 0%, Clip at no
cut; an edit applies the effect, and the slider back at zero removes it. An axis alone is not
an effect. The view settings own both effects, so a mode reset preserves them and a restored
effect reappears on the model. Clip's slider, left to right, cuts deeper through the original
bounding box; pose, animation and Explode never redefine the range. It shows the share cut
away, while the view stores where the plane stands (`clip.at`, in millimetres), so a model
edit leaves the plane where it was and the slider reads 0% or 100% if the plane ends up
outside the new box. Explode is offered only where there are parts to separate: a STEP
assembly and a GLB of several rigid nodes. A STEP part file has no Explode tile, as it has no
Model tree (`STEP_PART_VIEW_FEATURES`).

## The file sidebar and the tool stack

**The file sidebar** (`kit/tools/FileSidebar.jsx`) holds what there is to read of the file,
whatever tool is in hand — the strip is for using tools, the sidebar for reading the file: a STEP
assembly's **Model tree** (a part file, whose tree would be its one row, has none), then
**Position**, where the file has joints to move; a robot's **Links**, an `.sdf`'s **SDF**, then
**Position**, where a joint can be driven; a drawing's **Layers**, where it has four or more
layers or any block reference (a flat pattern's CUT and BEND has none): each layer's pen, name,
entity count and eye, its block references under it; and, after them, the shell's own **Animation** for a
file with routines (`kit/tools/playbar/AnimationSection.jsx`). A file with none of them has no
sidebar. It is a toolbar of its own at the view's top-left, 8px in, on the strip's line and of
its surface, padding and 24px tiles (`data-file-sidebar-tools`, "File sidebar"): one tile per
section, a tree's a tree icon named for it (Model tree, Links), Position's a spline, Animation's a
clapperboard, any other section's a page named for it. Preview offers its Position and
Animation alone, their tiles bare in its top-left corner; the rest stay mounted, out of sight.

- **One section at a time.** None is open as a file opens. A tile opens its section in a panel
  under the toolbar, 8px below it, and is pressed while it is open; another tile opens its
  section in the panel instead; a second press of its tile closes it, and so does the X that
  ends the section's head. The panel slides in from the left as a section opens with none open
  before, and back out as the last closes (200ms, none under reduced motion); from one section to
  another it stays where it is. Closed, the panel is out of reach (`inert`). Every section stays
  mounted, open or not, so a tree keeps its expansion, search and scroll. Nothing folds: a
  section is its head and its body.
- **Sections.** Each section is a `ToolPanel` drawn as one: a 24px head — its name 12px in from
  the panel's edge, what its body puts there (`ToolPanelHeadAction`: Position's and Animation's
  Reset), then its X — and its body. A tree's head is its filter instead of its name, the X
  after it. The section is its content's height and the panel as tall as it is, up to its cap;
  past that the whole panel scrolls, as one, the head pinned to its top
  (`data-pinned`). A tree's rows are mounted as that scroll brings them into view
  (`kit/inspector/VirtualRows.jsx`).
- **Filter.** A tree is headed by its filter ("Filter model", "Filter links": "Filter…"), in place of a title,
  always there, a tree row's 24px and 11px text, its icon over the rows' glyph column
  (`primitives/tree-filter.jsx`'s `TreeFilterInput`, `dense`), its X clearing it once something
  is typed, Escape too. The model tree's filter is followed by "Loading…" while a part's faces load
  and **Show all** while parts are hidden. Every tree's search is one ranked flat search
  (`kit/inspector/modelTreeSearch.js`).
- **Size, each section's own.** A section's panel opens a tool panel's width
  (`TOOL_PANEL_WIDTH`, 164px) and as tall as its section, capped at the room under the toolbar.
  It is sized from its bottom-right corner alone, by Quick Edit's grip (`kit/tools/ResizeGrip.jsx`):
  width and cap together, by pointer, or by keyboard (a separator named "Resize file sidebar":
  Left/Right nudge the width and Up/Down the cap by 16px, Home and End take both to their
  bounds). Its width runs from 120px (`FILE_SIDEBAR_MIN_WIDTH`: room for a heading's name and its
  buttons; a tree's names truncate) to half the viewer, its cap from 64px to its room. One write,
  when the gesture lets go (or per key), never per pointer move; each section keeps its own size
  (`sidebar:<id>`), so the model tree may be wide and tall while Position stays narrow.
- **On a phone** the sidebar is one touch tile, **Sidebar** (a panel icon,
  `data-file-sidebar-toggle`), at the left of the strip's line, the strip padded clear of it on
  both sides and keeping to its tools (`FileSidebar`'s `phone`). It opens one panel on the section
  last open (the first, at first): its top a row of tabs, one per section with its tile's icon
  (shadcn's `ToggleGroup`, `data-file-sidebar-tab`), and the panel's one X at that row's right end
  (a section's head then has none; a panel of one section has no tabs and keeps its head's X).
  The panel runs down to the view's bottom inset, or is as tall as its section if that is less,
  stopping above Quick Edit's peek (`--cad-quick-edit-peek`), at a phone's own width (288px,
  within the view's inset), with no grip. Its text is the panel's one size (13px, as the
  Display menu's), its tree rows 36px with 16px glyphs, its filter, dropdowns and value fields
  32px (`globals.css`). In Preview its tiles are its top-left's, as on a desktop.
- **The layout is the person's.** The section sizes are one of the tab's settings, across its
  files (`CadPreferences.toolStack`: `{ panels: { [id]: { width?, height? } }, collapsed: { [id]: boolean } }`,
  a section's panel under `sidebar:<id>`, kept beside the appearance; any other key a stored
  record carries is dropped). `panels` holds only what a person set; `collapsed` is the tool
  stack's folded panels. Which section is open is not kept: a file opens with none. A new tab (a
  cleared record) puts everything back at its defaults.

**The tool stack** (`ToolStack`) is the column under the strip and the sub-toolbar, centred
with them, for a renderer's own `toolPanels`. STEP and the robot renderer hand none: their
tools' controls are sub-toolbars and what there is to read of their files is the sidebar's.
Its panels follow these rules:

- **Two kinds of panel.** A `resizable` panel is the person's to size, on its own; every
  other panel is *fixed*: one width, its content's height, and no grip.
- **One width.** Every panel opens at `TOOL_PANEL_WIDTH`: 164px, a strip of six tools (six
  24px buttons, 2px gaps, 4px padding and a 1px border). A fixed panel is exactly that wide; a
  resizable one is only ever made wider, up to half the viewer. The panels hang left-aligned
  in the column, each at its own width. Content truncates to fit; it never widens a panel.
- **Heights.** A panel is exactly its content's height — never padded to a minimum. A
  resizable panel has a *cap* the content grows up to and then scrolls inside: it opens capped
  at the stack's own height (`toolPanelDefaultHeight`). A cap is never a floor.
- **One grip, on a resizable panel only**, the sidebar's: its bottom-right corner, Quick
  Edit's grip, moving its width and cap at once, a separator in the tab order named after its
  panel, keyed as the sidebar's is. A folded panel has no grip: there is no height to set.
- **Never past the viewer.** The column stops 8px above the cube's line
  (`VIEWPORT_STACK_BOTTOM`, `calc(6rem + 16px)`). When the panels need more, a `"tree"` panel
  gives way first, down to 128px or its content, then the `"details"` panels together, each in
  proportion to its height, down to 96px or its content; a `"fixed"` panel keeps its height.
  If what cannot give way still does not fit, the column itself scrolls — a panel is never cut.
- **Headings.** A panel's heading row reads as Display's section headings do (11px, regular,
  `TOOL_PANEL_HEADING_TEXT_CLASS`), 28px tall, 8px in: a title, a summary where there is one,
  then at its right end its own actions, the chevron where it folds (up while open, down while
  folded) and an X where it has something to remove. Every small button in a heading is 20px,
  2px apart and 4px from the edge. A panel can end in one full-row button under its body,
  which never scrolls (`footer`, `ToolPanelFooterButton`).

- **Surfaces.** Three, defined once (`lib/floatingSurface.js`), with one border: the
  tool strip, its sub-toolbars and the stack's panels, which stay up beside the model, share
  `FLOATING_CHROME_SURFACE_CLASS` — the background at 30% and barely blurred
  (1px), so the model behind them is easy to make out; every menu and popover
  over the viewport, the app menu and Display included, share `FLOATING_SURFACE_CLASS` (the
  background at 75%, blurred), so their text never competes with the model; and the file
  sidebar, mostly text but up for as long as the file is open, is between them
  (`FILE_SIDEBAR_SURFACE_CLASS`: 55%, a 4px blur).
- **Scrolling.** Every scroll region in the viewer's chrome — the file sidebar, a panel's
  body, the stack's column, the explorer, a menu, the alert card — is the
  `ScrollArea` primitive (`primitives/scroll-area.jsx`, shadcn's): thin overlay
  bars in the theme's colours, shown while the pointer is over the region. No
  native `overflow-auto` scroller in chrome; `src/designSystem.test.js` holds it.
  The home (the model library) is a page, not chrome: it scrolls as a page does,
  with the platform's scrollbar, and only when there is more of it than fits.
- **Nothing opens elsewhere.** A pick shows as Quick Edit's chips; the sidebar is on screen
  under every tool. No pick or tool opens or closes the explorer, on desktop or mobile.

Tree rows inset their backgrounds 4px from the panel's edges, and the search box
shares that inset. A tree in the file sidebar (Model tree, Links) is dense (`TreeRowSurface`'s
`dense`): 24px rows in the panels' 11px text, and ONE light 12px glyph per row in one
column, as the explorer has: a subassembly's or folded group's disclosure chevron, turned down
while open, or a part's box (Links draws its chevrons alone), 4px before the name. The glyph
column starts 5px in from the row's left end (`TREE_ROW_INSET_PX`), centred under the find
field's search icon and as far in as the icons of a row's actions sit from its right end, in the
STEP tree and the explorer alike; each level adds
the explorer's compact indent, 10px (`TREE_INDENT_PX`), its rows hung from a faint line under
their owner's glyph (`TreeRowGuides`), as the explorer's are; its search box is its section's head. An assembly row's
actions, shown on hover and kept while they are on, are **Isolate** then the **Hide/Reveal** eye; a part file has no
Isolate. A Links row that draws something — a link with visuals, or one visual —
has the eye alone, in its search hit too: a link's hides its own visuals, never its
child links, and on a partly hidden link hides the rest. They float over the row's right end rather than taking width from it:
the name runs the row's full width and, while an action shows, fades out half a
rem before them (a mask, `ROW_NAME_UNDER_ACTIONS`), so nothing is drawn behind the
buttons and the row keeps its own colour.
Model and link finds and the explorer's filter share `TreeFilterInput`; the explorer's rows are compact
24px lines, as the trees' are, but in 12px text.

**Mobile** is below 600px of FileViewer width (Material's compact window class) — the one viewer breakpoint
(`useViewerMobile`); chrome never uses window breakpoints, nor the pointer's kind: a small window
is worked as a phone is. What a finger reaches is the gesture's own (`pointerType`): a touch takes an
edge from 20px off (an edge within 16px wins over the face under it), ink, a measurement and the
eraser's ring from 16px (`TOUCH_HIT_PX`), and a joint's knob from 22px; a mouse keeps its few px.
On a phone every slider is a 36px band with a 20px thumb, and the selected ink's bar has 36px
buttons. A pinch zooms at the touch speed from the first gesture after a load. A phone is read at arm's length
and worked with a finger, so its chrome is one step up the scale, after the platforms' own
guidance (Apple's 44pt and Material's 48dp touch targets, an 11pt type floor and 15-17pt body
text, and iOS Safari zooming into any field under 16px): type 12, 13, 14 and 15px for `text-micro`,
`text-tiny`, `text-xs` and `text-ui`; text entry 16px; menu, select and tree rows 36-40px; the
navbar a 48px row of 36px controls; the strip and the sub-toolbars 36px tiles (the strip one row,
**More tools** holding what does not fit; Annotate's controls its chevron's menu, with no row).
The scale is set once, in `globals.css`, for the whole page while a phone's view is on it, so a
portalled menu, select or hint is the same size as the chrome it opened from. There is no view
cube; the file sidebar is one tile at the strip's left, its sections tabs of one panel; and
Quick Edit is a bottom sheet (see
[Quick Edit](#quick-edit)). The explorer is the same popover, never wider than the window less
1rem. The shortcut hint is hidden.
Touch works for every tool: one finger orbits, two pan and
zoom, a tap picks; a pinch, a cancelled pointer or a camera drag is never a
pick.

## Display settings and section primitives

Display is not a tool. Its tile ends the strip after the strip's rule, between Projection and
Preview, and shows the current mode's sphere icon. It opens a stock shadcn dropdown menu
(`DisplayPopover.jsx`): a muted **Display** label, the modes as a `DropdownMenuRadioGroup`,
a separator, then **Grid**, a `DropdownMenuCheckboxItem`. On a phone the strip's **More**
menu has a Display row whose nested submenu is the same list (`DisplayMenuItems`), with no
label. Checks sit at the row's right end. Choosing a mode closes the menu; ticking Grid
toggles it and leaves the menu open (`onSelect` prevents the close). Clicking outside or
pressing Escape closes it. Opening it leaves the active tool and its controls in place. A
2D view has no Display or Preview control.

Display is a choice of mode and the Grid switch, and nothing else: a mode has no settings
of its own, and there is no settings page. The modes, in order, are **Solid** (shaded with
the model's CAD edges, the default), **Shaded** (no edges), **Parts** (Solid with each part
its own colour), **X-ray**, **Hidden line** and **Wireframe**, filtered by the view's
injected capabilities (`viewFeaturesForKind`, `DisplayModeOptions.js`): a STEP assembly
offers all six, a STEP part file all but Parts, and a file without CAD edges (STL, 3MF, GLB,
a robot) Solid, with Parts when it has several parts, objects or links. **Grid** draws the
measuring grid in every mode, off by default. Each row has its icon, the sphere drawn as the
mode draws a model (and a tile of floor grid for Grid). Render is no display mode: Preview
draws the model in Render whatever the file's mode, with its own settings (see
[Preview](#camera-animation-and-preview)). Per-file storage keeps the mode and the grid;
old-shaped stored display settings are dropped setting by setting, never migrated.
Projection is a menu of its own, shared, orthographic by default; Preview's Render resolves
to perspective while preserving the shared choice.

Preview's settings panel (`PreviewSettings.jsx`, its body `PreviewRenderSettings.jsx`) is
the one settings form: Orbit, then Render's Part colours, Lighting, Background and Floor.
It shows all groups under static section headings and dividers, with no collapsible
sections or cascading settings menus. A heading is 24px of regular `text-tiny` in the
foreground colour, a rule above every one but the first. A feature that switches on and off
(Orbit, Floor) is the checkbox at its heading's right end, the title naming it; there is no
separate row for it. While the feature is off its section is that heading alone. Every
setting is one 24px row: its label in a 4rem muted column, its control filling the rest, so
a form's controls start on one line. A label is short under its heading ("Colour",
"Opacity" under Floor); the control's accessible name stays whole ("Floor opacity"). A
dropdown or colour is as wide as its value, at the row's right end. Sliders are shadcn's,
as everywhere, with a committed value field after them. By part's palette is a row of
swatches, then add and remove. Choices use Select controls. Continuous values use compact
slider and committed-number fields; their keyboard input stays with the field. Colours
retain swatches and a custom colour picker. Floor is on by default, at the model's Z=0
plane. A long form scrolls within the available viewer height. A nested Select or colour
picker owns Escape and outside interaction before its parent surface. The last item is
**Reset to default**, disabled at Preview's defaults; it removes only Preview's overrides,
never the display.

Preview's settings use shared settings field primitives under their static headings; other inspector
sections retain their own disclosure rules. Hover, focus and rendering never write
settings. Light and dark are the app menu's Theme.

Type comes from the token scale only (`text-micro` 10px, `text-tiny` 11px,
`text-xs` 12px, `text-ui` 13px, a phone's a step up: see [mobile](#the-file-sidebar-and-the-tool-stack));
no pixel font sizes. Settings controls and the
menu labels use `text-tiny`, regular weight;
panel headings use 12px. Sections use 8px gutters and bottom insets
and 4px row and column gaps. `FileSheetFieldGrid` owns horizontal spacing; its
children never pad again. Menu, select and context-menu typography comes from
the primitives, portals included. Selected values show their icon where it
means something.

Use `FileSheetSliderField` for a useful bounded range with a committed number
input, `FileSheetNumberProperty` for other scalars, `FileSheetColorProperty` for
color with opacity, and ordinary Select controls for choices. Drafts stay local
until Enter or blur; Escape cancels. Clamp at the owner's write boundary, which
sliders and number inputs share. Omit a visible label only where the value or
icon is unambiguous, and always keep the accessible name.

## Settings

Settings are the person's, never a file's, and live in the app menu: one dropdown
(`file-viewer/navigation/AppMenu.jsx`) on the floating surface, 15rem wide, from the
navbar's logo over every file (FileViewer builds it from the host's `links`, the
`appSettings` `CadViewer` hands it and `environment.platform`, while a model loads and after
it failed to as well); the home has no menu. Its rows, a rule between each group, are only
what the host supplies:

- **Back to files**, where the host has a home
  (`navigation.home`): it shows the home in this view. The home's own menu has none.
- **Theme**, where the host hands the person's colour scheme (`colorScheme`, both apps): one
  row, its name and then **System**, **Light** and **Dark** as a segmented control of their
  glyphs (each a radio item, named), the one in force lit; a press changes it without closing
  the menu. The web's System follows the OS and is
  the tab's; the CAD app's follows its host's theme, Light or Dark overriding it for as long as
  the view is open. The web's home, which has no menu, keeps its light/dark button
  (`colorSchemeControl`) last in its row.
- The host's own on/off settings (`appSettings`), a checkbox item each, in the order they
  come, checked at the right; a press turns one without closing the menu. **Share
  usage stats**, in both apps.
- **Send feedback**, where the host has a tracker (`links.issues`): a link to a new issue
  titled "Feedback: " for the person to finish, naming the version and the platform, with
  no label (what is said may be a bug, a request or a question). Then **GitHub** and
  **Discord**.
- Last, in gray, a footer: "v<version> · Made by @<handle>" — the version a link to its
  release notes, the handle one to the host's X account. A build that is not the release's
  own adds its id to the version: `v0.7.15-dev.b80844940`, the commit it was built from.

Nothing of a file is in it: a file's view is
[Display](#display-settings-and-section-primitives)'s. Every setting is the person's, not a
view's or a tab's: the host keeps it where every view of theirs reads it (both apps: their
settings, `settings.json` in cadgen's state directory), and a view reads it again whenever
the person comes back to the page.

## An FEA result

A GLB that `cadgen fea solve` wrote is a result: its mesh carries every field, the true
displacement, a plain-language summary, the study it was solved for and the source face of
every triangle (`glb/feaResult.js`). The study is read once there (`result.study`: what every
analysis shares, and what one alone echoes, an electromagnetic study's voltages, currents, coils and
AC source, a composite's layup and ply materials), and every analysis reads it from there, never the
file's raw echo. Its choices are Study's, and what the colours mean is on
the view; the view's own settings are any GLB's. It has no mode of its own.

The FEA viewer is a chunk of its own (`glb/feaView.jsx`: its surface, `glb/FeaSurface.jsx`, Study, the
colour bar, the markers, `feaResult.js` and `fea/`), which `GlbRenderer` loads with one `import()` only once
the loaded scene carries a mesh `cadgen fea solve` wrote (`generator` and `fields` in its extras), and then draws
the file with its surface instead of the GLB's: one shell, the same tools, the result's own layers. A plain
GLB never fetches it and renders as it always has; a result waits as the file loading until the
chunk is in (loaded once, for every result after it), so it is framed once, as it is drawn.

A result is of one analysis (`extras.analysis.type`; none is static): Strength (static),
Vibration, Buckling, Heat, Heat over time, Heat stress, Shaking, Random vibration, Shock, Over
time, Fatigue life, Drop (estimate) and the Tier 3 "lite" Flow, Drop impact, Permanent bend and
Contact. What the viewer does per analysis is one registry entry each (`glb/fea/analyses/`: its
word, the noun its takeaway uses, its tier, the check kinds it judges, What you see's controls
with no view, its setup groups, its routine, its marker kinds and its markers' gate's title), per
check kind one row of `glb/fea/checkKinds.js` and per field one of `glb/fea/fields.js`; a series of
frames (modes, times, frequencies) is `glb/fea/series.js`. Everything below holds for every
analysis; where one differs it says so. A static result, and one written before analyses were, is
exactly as it always was.

- **Its tools, Parts and Study.** A result has every GLB's tools (`kit/tools/sceneTools.jsx`): Select first,
  picking the result's faces rather than its nodes, then Annotate, Measure and Clip (below). Study, and an
  assembly's Parts above it, are sections of the file sidebar (`glb/FeaStudyPanel.jsx`, see
  [The file sidebar and the tool stack](#the-file-sidebar-and-the-tool-stack)), whatever the tool: each a tile
  that opens it, in the Links tree's rows, as a STEP's Model tree is, and none open as the file opens.
  - **Parts**, only for an assembly of six parts or more (`parts` in the file, `feaShowsParts` in
    `glb/feaResult.js`; a single part's result has none, and looks as ever). Under six, the parts
    are told apart on the model: a face picked there names its part, and its chip's card says the
    part's material and what it holds; the findings name the joints. The study's `view.show.parts`
    shows or hides it whatever the count. One row per part, its name, then its material and "holds 1.5×", or "yields"
    under 1. Under each part, the joints it is in, each naming only the
    OTHER part ("↔ chassis bulkhead"), then "bonded · 88 mm²", with "· 0.1 mm gap closed" when a gap
    was closed to bond it, or "not connected" and how far apart for a free pair. A joint is so under
    both its parts, and either row is the same choice (both rows show it chosen). The weakest part
    (the one the file names, else the lowest factor) opens with its joints and the rest start shut,
    so four parts and their joints do not fill the column; each opens by its chevron. Names and
    details wrap between words, never cut off.
  - **Study** leads with the answer and reads the study in plain words, technical terms after them
    or in hints, so a person who is not an engineer has the answer in two seconds. Its sections are
    the study's to pick (`view.sections`, `feaSections` in `glb/feaResult.js`: the verdict, the setup,
    What you see and Details, in the view's order, leaving out what it omits and skipping a name the
    viewer does not know), each only where the file has something for it; with none named, all four,
    top to bottom:
    - **The verdict** (`glb/FeaVerdict.jsx`, from `feaVerdict` in `glb/feaResult.js`), a block on
      the status tone's own background at the top of the panel's body, in the theme's status tones:
      error (a crossed circle), warning (a triangle), success (a ticked circle). Three parts, top to
      bottom:
      - **A headline**, in the worst check's tone. One check says it in its own words: a stress
        check **Too weak** under a safety factor of 1, **Close to the limit** under the study's
        margin (`study.margin`, else cadgen's 2) and **Strong enough** from it up; a displacement
        check **Moves too much**, **Close to the limit** (within a tenth of its limit) or **Stiff
        enough**. Several say how many fail ("Fails both checks", "Fails 1 of 2 checks"), else
        **Close to the limit** or **Passes all checks**. A load path that stopped short of the full
        load (`collapsed`) whose checks all hold at the last load it carried is headed **Stops short of
        the load**, in the warning tone, never a pass.
      - **What it means for the load**, one line: how many times this load the weakest check takes
        before its limit, floored ("OK only to 0.4× this load" under 1, "OK up to 1.6× this load"),
        the noun the analysis's ("this shake", "this drop", "this heat"); buckling's load factor
        falls as the load grows ("OK up to 13× this load"); a check that grows with the square of what
        drives it (`scaling: "quadratic"` on the check: a magnetic force's stress and displacement, with
        the current squared) takes the square root of its room ("OK up to 218× this current", not 47619×;
        a spinning rotor's stress, with the speed squared, likewise). An analysis not linear in its load
        (creep, a permanent bend, contact, a bolted joint, a composite, a drop impact, flow, flow and
        bending, two fluids) never says a load multiple: cadgen tags its checks `scaling: "none"` and its
        registry entry says `scaling: "none"` for a file older than that, so the worst check's own
        sentence is the line ("Steady creep · Peak 100 MPa, limit 250 MPa"); of the checks as bad as the
        worst, the first the person named in the study's view (`view.checks[].label`, "Bore swell": their
        question) says it, before a default one that uses more of its limit. Where the worst check's kind does not
        move with the load (a frequency, a temperature, a pressure drop), its own sentence instead
        ("First mode 85 Hz, must stay above 60 Hz", "Hottest 84 °C, 16 °C under its limit"). The
        line says how far to trust it, and nothing else: an estimate (Tier 2, drop) leads with
        "Estimate · "; a Tier 3 analysis leads with its short limit word ("Laminar · ", "Rigid floor · ",
        "Lite · " where it has none), and a flow the file warns ran past the laminar range with
        "Laminar · unreliable above Re 2000 · " (1000 for an external flow, or the number the warning
        names); a fast gas flow the file warns of (`analysis.mach` not `checked`) adds what it ran past
        after its word, "Ideal gas · past Mach 1.8 · " (the limit the file names), or "Ideal gas ·
        supersonic outlet · " where the peak is within it but the gas leaves faster than sound. A
        load path that stopped short of the full load (`collapsed`, the analysis's `stopCaption`) leads
        with that before anything else (each check is still judged on its own number where it stopped: a
        bolt under its proof load holds): a contact or bolt solve "Stops at about 20 % of the load · ", a
        permanent bend "Collapses at about 70 % of the load · " (the file's sentence, else from its
        `load_percent`), then its limit word and its worst check. Two fluids stopped at its time limit
        (the file's "Stopped at its time limit at t = 420 ms of 1.5 s ..." in `analysis.warnings`) leads
        the same way, "Stopped at its time limit at 420 ms · Laminar · ", its checks' labels ending
        "(stopped at 420 ms)" and a pass shown close. Two fluids that spilled (the file's "Spills over the
        brim: ..." in `analysis.warnings`, its fill level check failed by the spill) says that as the
        takeaway, never the fill level's line, which reads at most the brim: "Laminar · Spills over the
        brim: 2.3 mL left the tank (6.4 % of the liquid)". Two fluids' fill level is the highest point
        of the liquid's surface anywhere inside, so its row may read higher than a probe's curve. A
        contact (or bolt) solve whose forces did not settle at a load step (`analysis.unsettled`)
        leads with that next, "Not reliable · contact did not settle at 80% · ", the
        first step it names; its checks are ordinary fails, shown as any are. A result that took a step to fit the run that cost some accuracy (`extras.fit`, a
        step with an accuracy note) ends with " · adapted". A Tier 1 result that took none is as
        ever.
      - **Each check, the same way**, worst first (failing before close before passing, then the
        checks the person named in the view, in their order, then the most of its limit used), under a hairline: its icon and name in its own tone (its name in
        the person's words, "Bulkhead top sag", or Strength), a thin bar of how much of its limit it
        uses (a `meter`: filled to the value over the limit, held at full past it with its end
        striped, and for a stress check a tick at the margin, which the meter's text names), and its
        value against its limit ("1.04 mm, limit 0.5 mm", three figures for a displacement: 1.04 is
        not 1; "405 MPa, limit 276 MPa", the limit an assembly's weakest part's yield). An electric
        field whose peak is out in the air (`where.in: "air"`, the part beside it `where.near`), past what
        the colours on the parts' surface show, says so: "Peak 4.5 kV/mm, in the air by hv-rod, limit 3
        kV/mm". An analysis may add a muted hint under a check's line (its registry entry's
        `checkHint`): heat stress, where the file finds the peak on a clamped edge (the
        `singular_clamped_edge` finding, written where its colours stop below that peak), judges strength
        (and the headline's multiple, through the file's safety factor) on the stress a little away from
        the edge, where the colours stop, the check keeping the edge's own peak (`edge_peak`), and says under
        Strength "Judged a little away from the clamped edge: the peak there, 1882 MPa, is a singularity
        that grows as the mesh is refined"; a file older than that, judged at the edge, says "Peak at the
        clamped edge: a singularity that grows as the mesh is refined. Read the stress a little away from
        the edge". A bolted joint's slip says which way it goes ("Sideways 950 N, friction holds up to 1
        kN"; slipping, where the two are equal, "Sideways 2 kN, at the friction limit: slips"; past it, "…friction holds only 2 kN"). An analysis may
        also add rows of its own with no limit (its registry entry's `facts`): a piezo resonance, each mode
        ("Mode 1", "6.5 kHz, anti-resonance 7.1 kHz, k_eff 0.40", `analysis.modes`), in no tone and with no
        bar, after any checks, each chosen with the whole result and showing its mode; with no checks
        they are the verdict, headed by the first ("First resonance 6.5 kHz", "Linear · Anti-resonance
        7.1 kHz, coupling k_eff 0.40"), in no tone. A magnetic result's force on each part is such a row too
        (`analysis.forces`: "Force on the plunger", "0.424 N down, its magnetic pull"; on a coil "the current
        in the field"); with no checks, "Pulls the plunger with 0.424 N". A line is kept whole in pieces that break between them, never inside a word ("Factor
        4.0 at 100 million cycles, needs 1.5" breaks before "at"). Each check is
        chosen on a press, as Study's rows are: it tints the faces it is over (`faces`), else the face
        it peaks on (`where.ref`), else names the whole result, and carries its sentence into Quick
        Edit ("Tip sag fails: moves 0.62 mm, limit 0.5 mm (OK only to 0.8× this load)"; an
        assembly's stress check names its part there: "Strength fails in bulkhead right support
        block: ..."). A check whose value occurs at a frame of the result's series (`at.frame`: a
        mode, a moment, a frequency) also shows that frame when chosen: the mode picker or the
        scrubber moves there (with neither, the view still shows it), so "Motor speed" opens mode 2.
      Everything follows the load shown (`load_scale` k): each value and share of its limit is k
      times the solved one, so a check, and the headline, can change its word. With no stress it
      says **No stress** and "Check the load reaches the part", in no tone and with no checks; at a
      load of 0, **No load**. The checks are the study's (`extras.checks`, `feaChecks`: each judged
      by cadgen, value against limit, `ratio`, `status`), a kind the viewer does not know skipped; a
      result older than them has the one stress check, derived from its safety factor, so it says
      what it always did. A result with a stress but no safety factor and no checks has no verdict.
      "No stress" is the static family's alone (static, heat stress, drop): another analysis with no
      checks it knows has no verdict.
    - **The setup**, read as sentences, each heading muted with, in the disclosure column, the glyph
      its marker is drawn as on the model (`glb/feaGlyphs.jsx`, lucide's grid at the trees' light
      stroke): **Held at** (a cone pointing into a face, the fixtures' grey), one row per fixed face
      (a fixture of `type` "fixed", or none given), its name alone ("Face 17"; in an assembly "post ·
      face 17"); right after it **Slides on** (the same cone on a plate that rolls on the face, the
      same grey), one row per face of a roller fixture (`type` "roller", a frictionless sliding
      support), named as Held at's are, its hint "May slide along the face, not move off it", chosen
      as Held at's are, tinting its faces and its markers ("Slides on face 3"; loaded too, "Sliding
      and loaded face 3"); every analysis that says where it is held says where it slides;
      **Pushed** (an arrow with a cone
      for its head, the loads' ink), one row per load, how much and which way ("2500 N down": "down"
      and "up" are CAD Z, else "along −X" or the unit vector; or "2 MPa pressure"), its faces under
      it by name, shut until its chevron opens them (choosing the load row still tints all its faces
      and its arrows); and **Made of** (a swatch), the material's name ("Aluminum 6061-T6"; its
      yield is the verdict's to say). Each material is called by its display name, cadgen's: a table
      entry's ("PZT-5A", "Steel (structural, generic)", also for an object that extends it, `{"name":
      "pzt-5a", "piezo": ...}`), or an object's own `name`, tidied as cadgen writes it ("Soft silicone",
      "Copper C110"; a file older than that, its first letter capitalised). In an assembly whose parts differ
      in two or three materials, each is named inline with its parts ("Copper C110 coil, Stainless steel
      304 shaft"; a material of three parts or more with how many, "Steel (3 parts)"); past three,
      "Mostly Aluminum 6061-T6" where one material has most of the parts, else "4 materials", each
      part's own in its hint; every part's own is in Parts and a picked face's chip too; a part
      with none of its own takes the study's. Every
      analysis's assembly says this (cadgen writes each part's name and material, `parts`, where an
      analysis has no per-part results of its own: electromagnetic, piezo, flow), and so names a face
      by its part ("upper · face 1"). The
      material row is chosen like a face, tinting nothing: it carries the whole result (every part in
      an assembly) into Quick Edit with what it is made of ("Made of Aluminum 6061-T6 (yield 276 MPa)",
      or each material with its parts). A
      heading neither chooses nor folds; its rows hang from a faint line under its glyph. A face or
      material row too long for the one width wraps between words, never cut off.
      A body load is Pushed's too, a row of its own with no faces ("1 g down", "5 g along +X"),
      chosen with the whole result ("Its weight, 1 g down", "Accelerated 5 g along +X"). Another
      analysis's setup is the groups whose entries its study records, in this order, each in the
      same two tones as its marker: **Held at**; **Slides on**; **Kept at** (a thermometer, grey: each fixed
      temperature, "25 °C", its faces under it); **Pushed**; **Heated** (a flame, ink: "15 W",
      "2000 W/m²", its faces under it); **Cooled by air** (wind, grey: "Air at 25 °C", how well it cools
      its hint, "Heat transfer coefficient 10 W/m²K"); **Shaken** (a wave, ink: "1 g along Z", "At
      random along Z", "A shock along Z", chosen with every face that holds it, rollers' too, where
      the shaker is); **Dropped**
      (a drop, ink: "1 m drop", how it stops its hint, the faces that land under it); **Flow in/out**
      (the flow, ink: "In 0.5 m/s at the low X side", "Out at 0 Pa, the high X side", chosen with the
      whole result); two fluids' **Filled** ("Half full of water, shaken 0.3 g along X"; a completely
      full inside, which has no free surface and is solved as the liquid's flow alone, says so in its
      hint: "Completely full: solved as single-fluid flow, no free surface"); **Rigid floor** (a plane, grey: "Facing up", "Under the drop"); **Crack** (a
      plane: "2 mm edge crack on face 4", its largest K its hint, "K 18 MPa√m at the deepest point",
      chosen with the face it opens from); **Made of**. An
      entry on faces is chosen as a load is, tinting its faces and its markers and carrying what it is
      ("15 W of heat into face 7", "Kept at 25 °C on face 1"), its faces shut under it. A picked face's
      chip's card says these too ("kept at 25 °C; 15 W of heat in", "cooled by air at 25 °C").
    - **What you see**: the controls the study's
    `view` chose (`feaControls` in `glb/feaResult.js`), in its order, with its labels, ranges and
    units, each a generic parameter row drawn by the same `parameterRow` as Position's joints
    (`kit/inspector/parameterRow.jsx`), a sentence-long label wrapping between words on its
    value field's line and the slider the row's whole width under them (`wideLabel`), so the
    narrow panel still gives the slider room. A control the view gives a `when` shows only while a
    check fails or is close (`failing`) or only while every check passes (`passing`), judged live at
    the load shown (`feaShownControls`); a hidden one keeps its value and acts at its default meanwhile.
    The load control's own `when` is judged at its default load, where it opens, so dragging it never
    hides it: a load slider shown while the part fails stays while the person drags it to a load that
    passes. What each moves is the viewer's, from a closed set (`drives`): **field** (a select
    of the fields the file carries, in plain words, as the colour bar names it too: Stress, Displacement), **deformation** (how many times the displacement is drawn,
    "×12.0"; its value box as wide as the value needs, so "×9500000" is never cut off; a result whose
    displacement is under a ten-millionth of its diagonal, `NEGLIGIBLE_MOTION` in `glb/feaResult.js`, a
    magnetic force moving a plunger nanometres, has no deformation control at all and is drawn at
    rest, whatever its view names), **load_scale** (the load as a multiple of the solved one, "×1.50"; only where the
    analysis follows the load, `scalesWithLoad`: never for a frequency, a temperature or a flow) and **threshold**
    (values of its field under it drawn neutral grey, "138 MPa"); and over a series, **mode** (a
    select of the frames' own labels, "Mode 2 · 118 Hz", for modal and buckling; a view's `default`
    names a mode by its value), **frame** (a scrubber along the frames' values, "Time", "Frequency" or
    "Load step", that snaps to the nearest frame where it is let go, its value field saying the
    frame's label, "12 ms"; it runs along the frames' places where their values do not climb) and
    **sigma** (a select of 1σ and 3σ, multiplying a random vibration's RMS fields, opening on the
    level the study judges at; the field select names its RMS fields at the level chosen, "Stress (3σ)",
    as the colour bar does). A frame's fields and deformation come from the attributes the
    series names for it (`glb/fea/series.js`), frame 0's being the fields' own; a field the same in
    every frame keeps its one attribute. A control whose `drives` or type
    the viewer does not know is skipped. With no `view`, or none of its controls the viewer can draw (an empty list, or all from a newer cadgen), What you see is the analysis's own (`defaultControls`), and a preset may set those. A view that picks the field but names no deformation keeps the analysis's own Deformation slider after its controls. Fatigue opens on the fatigue margin where the life is capped everywhere (the part outlasts the material's data: one number, nothing to see), else on the life. For static it is as it always was: a Field select
    with no visible label over every field, opening on stress, and a Deformation slider with its
    committed number, from 0 to four times the file's own exaggeration. For another analysis
    (`seriesControls` in `glb/fea/controls.js`): a series of modes, Mode and Deformation; a series of
    times or frequencies, the scrubber, Field and, where the result deforms, Deformation; RMS fields,
    Field and Sigma; anything else Field and, where it deforms, Deformation (a temperature has no
    displacement to draw larger, so a thermal result has the Field select alone). A flow (Flow,
    Turbulent flow, Fast gas flow, Cooled by flow) offers **Speed** among its fields (`_speed`, m/s,
    from 0): the wall itself is still (no slip), so it is the fastest the fluid moves within a passage
    width of each wetted point, reaching the fastest point of the flow, so the speed a velocity check
    quotes ("1.31 m/s, limit 3 m/s") is the top of its colour bar. Cooled by flow's **Fluid
    temperature** is the fluid's mixed temperature across the passage at each wetted point, so it runs
    from the inlet's temperature to the outlet's the result reports, never the wall's own. When the view names
    `presets`, a **Preset** row leads What you see, the Position panel's Pose row (`KinematicsPoseRow`)
    labelled "Preset": Default, each preset (a full state: every control at its default but what
    the preset sets), and Custom once any control moves.
    - **Details**, shut until its chevron opens it: the mesh, its size ("Mesh 1.9 mm elements"), how
      it got there ("refined from 2.8 mm", "not refined") its hint. The mesh row is chosen as the
      material is, carrying "Mesh of 1.9 mm elements, refined from 2.8 mm" with the whole result.
      Then **Adapted to fit**, where cadgen took steps to fit the run to the machine (`extras.fit`;
      nothing is refused for size, so the run says what it changed): one row per step, in order, its
      words the label ("Coarsened the mesh away from the hole to fit: the peak is still meshed at
      0.8 mm"), wrapping, its accuracy note its hint ("peak stress moved 2.1 % between passes"). A
      step is chosen into Quick Edit with its words and its accuracy ("Adapted to fit: ... (peak
      stress moved 2.1 % between passes)"), tinting the faces it is about (the region kept fine, the
      features left out), else carrying the whole result. A Tier 3 result then has **Limits**, one
      row per sentence its model leaves out ("Laminar, steady, incompressible; no turbulence
      model."), each chosen with the whole result. A flow the file warns ran past the laminar range
      has that warning as its own row, first ("Re 4200 is past the laminar range: ..."). A fast gas
      flow has a row for its Mach number after it: "Fastest flow Mach 0.53", its regime and the Mach
      its solver is checked to its hint ("Subsonic, checked to Mach 1.8"), or where the file warns,
      the warning's sentence ("Mach 2.10 is past Mach 1.8, ..."). A contact solve that did not settle
      has its sentence as the first row of all ("Contact did not settle at 80% of the load: ...").
      An analysis with rows of its own (its registry entry's `detailRows(result, whole)`) puts them
      before the mesh: flow and bending's "Coupling: settled in 4 iterations", the change it reached
      its hint, or "Coupling: did not settle in 25 iterations" with "the last state, not an answer".
      Each is chosen with the whole result. The fit
      steps are findings for the agent too; the viewer shows them only here. Details shows for a
      result whose study was not recorded where it has steps to say.

    Each group shows only where the file records something for it (`STUDY_GROUPS` and
    `DETAIL_GROUPS` in `glb/feaResult.js`: a result kind with more to say adds a group there,
    touching no other), so a result written before its study was recorded has its verdict, if it
    has a safety factor, and What you see alone. Study keeps the sidebar's width: the verdict and the
    setup wrap to fit it, and its sections run in the view's order in the sidebar's one scroll.
  - **Framing.** The camera frames a result right of the chrome at the view's left (the strip, the file sidebar
    and the section open in it) and above the colour bar: whenever
    the viewport fits the camera (opening, Zoom to Fit, a reset) it reads how much of its width the shown
    panels cover and how much of its height the colour bar does (`runtime.framingInset`, `framingInset` in
    `glb/feaChrome.js`) and fits the model into what they leave, panned to the middle of it (`insetLeft`,
    `insetBottom` in `kit/camera/viewportCameraFit.js`); it orbits about that point, as after a pan. A section
    opened or closed later does not reframe; Preview, a view of its own, frames in the whole width.

  A GLB that is not a result has the same tools, its Select picking its nodes, and no Study.
- **Choosing faces.** A fixed face, a load or a load's face chosen in Study tints its triangles
  (two thirds of the way to magenta, which no colour of the ramp is, so it reads at either end
  of the ramp while the stress still shows through) and carries
  them into Quick Edit by the STEP the result was solved from, with what they are: "Fixed face
  17", "Slides on face 3", "2500 N load on face 22", and a face that is both "Fixed and loaded face 17". A press on the result under Select picks the face under the
  pointer the same way, called what Study calls it ("Face 3" for a face the study does nothing
  to). What is chosen is Quick Edit's chip, named as Study names it; one face's chip has a card under the
  ref it names: what the study does to it ("fixed", "slides along it", "2500 N load, down", "free"), and the
  copy key copies the STEP's path and the ref, as a STEP's Copy writes it. Escape, the chip's X, Quick Edit's
  clear and a press on nothing let go. In an assembly the card has one more row, **Part**: the part's material
  and what it holds at the load shown ("6061‑T6 · holds 1.4×", or "yields"), as Parts' rows say it, so a small
  assembly with no Parts section loses nothing.
- **Choosing a part or a joint** in Parts is choosing faces, for an assembly (`_PART`, `parts` and `connections`
  in the file). A part tints all its triangles and
  carries its ref into Quick Edit ("Part 'post'"); a joint tints the interface faces of both sides and
  carries them ("Bonded joint between 'post' and 'base'"), its two parts tinted lightly around them; a free pair has no faces, so it carries
  both parts' refs ("'post' and 'lid' aren't connected"). A part's or a joint's chip has no card, and
  in an assembly a picked face's chip is named with its part ("post · face 1").
- **A colour bar** floats at bottom-centre on Preview's playbar's line (`FEA_BOTTOM_LINE` in
  `glb/feaChrome.js`; `FLOATING_CHROME_SURFACE_CLASS`, no pointer events), in the tools view and in Preview
  (its view's overlay), one playbar's height higher in Preview for a result with a routine. It is only the scale, on one row 20rem wide (less on a
  narrow viewport): the field in Show's words ("Stress", "Displacement"; a field the file names for
  the view by that name, "Mode shape"; a sound's level, drawn on the surface, "Sound level at the surface",
  so it is not read as the level at a check's microphone), then its range and units
  along the ramp ("0", "47.3 MPa"). A signed field (a temperature, a pressure) runs from its own
  minimum ("20.0", "84.0 °C"); a log field (a life in cycles) says powers of ten ("10³", "10⁹
  cycles"); a per-frame field's range is the file's, across every frame, so the colours compare
  from frame to frame and the bar stays put while the frame changes; an RMS field says the level
  it is shown at ("Stress (3σ)") and its range is that many times the file's. A field whose worst is
  its lowest (a life, a fatigue margin: `lowWorst` in `glb/fea/fields.js`) is drawn down the ramp, its
  lowest red as a stress's peak is, and the bar's ends swap to say so ("Fatigue margin 100 … 4.09"). A stress whose colours stop below its
  singular peak (the field's `capped`: a crack front, a heat-stressed clamped edge) says its top as "≥361 MPa",
  and its title says the percentile and the peak ("Colours stop at the 99th percentile; the peak is 948 MPa");
  the verdict judges the peak, but where it is a clamped edge's in heat stress, which it judges where the colours stop. The load shown scales
  the range only where the analysis follows the load. What the numbers mean for the part is the verdict's, so the bar
  says none of it. It has no controls.
- **Findings stay in the file for the agent.** The result's checks (`findings` in the GLB's extras,
  the sidecar and the CLI's lines) are what the agent reads and acts on; the viewer raises no alert
  card and puts no icon in the navbar for them (a board's findings keep theirs). The verdict at the top of Study is
  the viewer's status. Only a failure to load has the alert card.
- **A load other than the solved one** (`load_scale` k; the study is linear, so it scales exactly):
  the colour bar's range is k times the solved one, the safety factor and every part's "holds" (in Parts and a picked face's chip) are divided by k, so a part
  can turn to "yields" (at no load there is no factor, and "holds" is left out), and the displacement is drawn k times further. The colours keep their place
  on the bar, which reads k times higher. A threshold compares its field at the load shown.
- **Its routine.** A result has at most one routine of the viewer's own, its analysis's
  (`routine`, played through `useGlbAnimation`'s own clips), looping as its Loop says: from the file
  sidebar's Animation in the tools view, and from Preview's playbar in Preview, whose scene shares the
  result's geometry, so the colours and the deformation a routine draws are drawn there too. Nothing is
  baked into the file: the viewer deforms from the vectors it carries.
  - Vibrate, and a Load ramp outside the static family (piezo's voltage, buckling's Buckle), draw the
    model at the Exaggerate value, raised where that would move its largest motion less than a tenth
    of its diagonal (`routineScale`, `ROUTINE_MOTION_SHARE` in `glb/feaResult.js`), so a small part's
    motion (a piezo bimorph's stroke, a disc's mode) is clearly seen; an Exaggerate past that is kept,
    and 0 stays 0. The static family's Load ramp is drawn as it always was, and Play's frames as the
    scrubber shows them.
  - **Load ramp** (the static family, a drop from before cadgen wrote its fall, a static piezo result's voltage going on; buckling's is called **Buckle**): in preview the playbar
    plays the load going on, from none to the load chosen, over two seconds, the colours climbing
    under the bar of that load and the deformation and markers following.
  - **Vibrate** (modal, harmonic, piezo's modes and sweep): one swing a second, the shape shown drawn × sin 2πt, out one way
    and back the other through rest; a harmonic frame turns through its phase, re·cos − im·sin, by
    its imaginary part.
  - **Play** (a series of times or load steps: heat over time, over time, a drop impact from before
    cadgen wrote its fall, permanent bend): the frames in turn over three seconds, each colour and position blended linearly into the
    next's. Two frames moved by the same vector (heat over time, whose displacement is the file's one
    in every frame) are that vector: Play then steps the colours alone, rewriting no position, normal
    or marker for a model that does not move.
  - **Ring** (sound's cavity modes): one swing a second, the chosen mode's signed pressure × cos 2πt
    on a ramp symmetric about 0 (± its largest magnitude, `symmetricRange`), so the mode's two ends
    trade colours through the cycle; nothing deforms. A sound sweep plays none. The air closed inside
    a part (`domain: "inside"`) is drawn as its own solid, the faces it wets alone (cadgen writes only
    those, `analysis.acoustic.shown: "air"`), as the part's own air is: the part's outside reads no
    pressure and would hide it. The walls around it are drawn as a faint grey outline (cadgen writes
    their edges, `analysis.acoustic.walls_mm`), whatever the markers' gate, so the enclosure reads.
  - **Tracers** (flow, turbulent flow, fast gas flow, cooled by flow, flow and bending: the file's
    `analysis.motion`, kind `tracers`, read by `readTracers` in `glb/fea/poses.js`, drawn by
    `glb/feaTracers.js`): dots carried along the paths cadgen traced through the solved velocity field
    from the inlets (as dense as the flow through them; an external flow's across the part's width),
    six to a path, each starting again at its inlet at the path's end, so the flow streams. They move at
    the real speed times one round factor, the median trip about four seconds on screen (a fast flow
    slowed, a creeping one sped up), and the readout says how long of real flow has passed and the
    factor ("12 ms of flow", "slowed 200×"). They are drawn as the markers are, solid in view and a
    faint ghost where the part hides them, under the result mesh, so the file's Clip cuts them, and a
    flow's preview keeps its cut (preview suspends it for every other result) so they stream inside
    the part it opens. A flow has no row: the playbar's Speed sets their pace.
  - None for steady heat, a static electric or magnetic field and a composite: what they show does not move.
- **A motion** (`glb/fea/motion.js`): a result whose part moves as a whole through time is moved as a
  STEP's kinematics is, not only played. Its analysis supplies the motion (`motion(result)`: its
  timeline, the moment it opens on, its named states, the words for the real time at each moment, a
  solved frame's moment), and the viewer draws it the one way for every analysis: What you see leads
  with a **Time** row (named by the motion where time is not its axis, `row`: Cycle, Phase, Load, Heat; a scrubber over the whole timeline, in place of a series' own scrubber, that
  stops at evenly spaced moments, the states and each solved frame, its value field the real time
  there), its states join the **Preset** row after the view's own presets (each a full state, the
  Time row at its moment), a chosen check jumps the Time row to its frame's moment, and its routine
  (`kind: "motion"`) plays the same timeline in preview, from the Time row's moment back to it when
  let go. The Time row has a **play** button beside its value field (`FeaStudyPanel.jsx`, through
  `parameterRow`'s `action`: a ghost icon button the joint value boxes' size, a play triangle hinted
  "Play the motion", a pause hinted "Pause" while it plays), so a person sees the motion plays without
  finding Preview: a press plays the same timeline in place in the tools view, once, from the row's
  moment (from its start where the row is at its end), the slider and the value field following it
  and the readout showing; a second press pauses it there, and dragging the row, choosing a preset,
  another result, another tool or entering preview stops it where it is. It honours reduced motion as
  the playbar does (only its `play` span). Preview keeps its playbar. The Time row's moment is the
  file's view (`motion`, written once chosen). With reduced
  motion (the host's `reducedMotion` or the system's), the playbar plays only the motion's `play`
  span, where the part stays put. A motion is drawn one of two ways, a drop's fall or a pose:
  - **Drop** (a drop estimate and a drop impact whose file carries `extras.analysis.fall`:
    `glb/fea/fall.js` keeps the time, `glb/feaFall.js` draws it). The part is drawn turned so the way
    it falls points down, the point it meets first on a see-through floor (the rigid floor's look,
    as wide; an impact's own floor marker stands for it while the part is on the floor). The
    timeline: it waits half a second at its height, falls under gravity at real time (1 m in 0.45 s;
    a fall under 0.4 s slowed to last that long), meets the floor, and the impact, milliseconds long,
    lasts about 2.5 s, slowed by a round factor (1, 2 or 5 × 10ⁿ): an impact's frames by their
    times, its centre of mass carried where the file says (`fall.centre_mm`); an estimate's load
    ramping to its peak and back as a half-sine over the stop it assumed. An impact that rebounds
    (`fall.rebound_m_s`) hops off the floor at that speed under gravity and comes back; it rests
    for a second, on its last frame's shape (an estimate at rest). The part is never drawn through
    the floor (an exaggerated squash lifts it), and on it once at rest. The Time row says the real
    time from landing ("−0.45 s" falling, "0 s", "10.1 µs", "At rest"); the states are Released,
    Contact, Peak (where it opens: an impact's peak frame, the middle of an estimate's stop) and At
    rest. Off the floor the markers and their labels are put away. While the routine plays, a small
    readout over the colour bar (`FeaFallClock.jsx`) says the real time in words ("1 m above the
    floor", "0.32 s", "0.21 ms after landing", "At rest") and, while slowed, by how much ("slowed
    2,000×"); with reduced motion it plays the impact alone.
  - **A pose** (`kind: "pose"`, `glb/fea/poses.js`; drawn by `paintPose` in `GlbRenderer.jsx`): the part
    stays where it is held and what it shows changes; at each moment the motion says the frame, the
    colours (scaled with its load, or its own values then: `recolorByField`'s `values`) and the
    displacement (vector attributes and their weights, drawn at the Deformation shown, or for a shake
    raised so its largest motion is a tenth of the model's size, `poseScale` in `glb/feaPose.js`, and the
    readout says "drawn 3,000× larger"). The readout says the real time and the slow motion while it
    plays. Every pose is drawn from what cadgen solved and wrote (`extras.analysis.motion`), never
    invented; where it ramps a linear result it says "ramped":
    - **Shake** (random vibration) and **Shock**: the part's motion relative to its shaker, a few mode
      shapes (hidden `_MOTION_MODE_n` attributes, each 1 mm at its largest) times their histories over
      the window cadgen sampled. A random shake is synthesised from the PSD (one line a hertz at its
      level, phases from a fixed seed: its spectrum and its g rms) and the modes answer every line
      exactly; a shock's base pulse is synthesised to match its spectrum (wavelets, as a shaker
      controller does, its match at each mode in the file) and each mode's answer integrated exactly.
      Slowed so the slowest mode swings about once a second, ten seconds at most. Time row; states
      Start (a shock's Pulse starts, Pulse ends) and Largest swing, where it opens; the readout adds the
      base's acceleration ("1.5 ms · base 3.2 g"). The colours are the field's (an RMS, a peak envelope).
    - **Load cycle** (fatigue): the load swinging between R times its peak and its peak (`ratio`), the
      stress (Show's **Stress**, `_cycle_stress`, the cycle's peak von Mises) and the deformation with it,
      the life and the margin standing (they are of the whole cycle). A static load four cycles, one a
      second (the readout: "the load gives no rate"); a sweep's at its frequency, slowed; a random
      shake's 23 cycles at 1σ, 2σ and 3σ in Steinberg's shares. Cycle row ("Cycle 2 · 100 %"); states
      Max, where it opens, and Min (a random shake's 3σ peak and trough); the readout says how many
      cycles the weakest point lasts.
    - **AC cycle** (AC magnetics): the field shown (eddy current, magnetic field) turning through one
      cycle at its real frequency, slowed to two seconds: each vertex's strength re·cos θ − im·sin θ from
      its real and imaginary parts (`_MOTION_J_RE`/`_IM`, `_MOTION_B_RE`/`_IM`), on the amplitude's
      colour range; a temperature stands. Phase row ("90° · 5 ms"); states Peak (the strongest point at
      its peak, where it opens), 0° and 90°.
    - **Tighten and load** (bolted joint): the bolt tightened from snug to its preload (the preload's
      solve ramped: "ramped") over two seconds, then the service load's solved steps, a second each,
      blended. Load row ("Tightening 50 %", then each step's label); states Snug, Preloaded and Service
      load; it opens on the series' default step, and a check jumps to its step.
    - **Heat up** (heat stress): every temperature the same share of the way from the reference to the
      solved one, the stress and the deformation growing with it (a linear result: each moment exact for
      that share; "ramped"). Heat row ("62 % of the heat"); states Ambient and Heated, where it opens.
  The tools view frames the part on the floor through its impact; Preview frames the whole fall,
  from its height to the floor (the scene's `previewBounds`), so the camera never moves while it plays.
  Preview frames the camera once, on the box the model is drawn in over its whole series and its
  routine as it plays (`glb/feaBounds.js`: every frame, a Load ramp from no load to the load it
  opens on, a Vibrate out both ways, each at the scale the routine plays at; a pose over its whole
  timeline, `feaPoseBounds` in `glb/feaPose.js`), so the moving part
  stays in view and the camera never zooms while it plays.
  Letting go puts the model back at the frame and load chosen. The colour bar steps up above the
  playbar while it is there.
- **Loads and fixtures on the model** (`glb/feaMarkers.js`), from the study the file records: on
  each loaded face one to five arrows (more on a bigger face), spread over it, each 8% of the
  model's diagonal long whatever the load, pointing along the force with its tip on the face (a
  pulling force stands on the face by its tail); a pressure's arrows run along the inward normal;
  a label beside each load's arrows, past one arrow's free end (a push's tail, a pull's tip: of several,
  the one nearest their middle, never the middle itself, which arrows all round a shaft or a shake held at
  both ends put inside the part), says its amount at the load shown ("300 N", "2 MPa"). A label is never
  drawn on, inside or behind the part. It stands at that arrow's own outer end, a few pixels on along it, its
  text running on the way the arrow points (centred over an arrow that stands up; `besideEnd` in
  `glb/feaChrome.js`), only where that end is in sight and the label drawn there lies over none of the model
  (two rays: from the eye to the end, and through the label); otherwise, and always for a marker drawn through
  or all over the part (a body load, a shaker, the air, heat), it is carried along the arrow's line out of the
  model's box by the nearer way (`labelOutside` in `glb/feaMarkers.js`) and on screen past the outline of the
  model's box (`pastOutline`: the hull of its corners), so "1 g down" stands beside the model and a load in a
  pin hole is labelled outside it. No label is drawn past the view's edge (it is drawn whole against it), under
  the tool strip, the tool stack and the file sidebar at the view's left (`chromeCover`: one there moves right of them) or over
  the colour bar (`colourBarCover`: above it), nor over another label: each in turn is nudged up or down
  clear of those before it (`settleLabels`), every frame, however the view has been turned. On each fixed face, small cones point into it; on a roller's face (Slides on), the
  same grey cone stands on a small plate on two balls resting on the face, pointing into it along
  its normal, unlabelled, drawn wherever fixtures are. They stand on the deformed shape as it is
  drawn, in two passes, the x-ray look: what is in view solid, depth-tested as the model is,
  and what the model hides as a faint ghost (a quarter opacity) over the surface, so a fixture
  under the base reads as under it, never as standing on the face in front; a load's label the
  part hides is ghosted the same way (a ray from the eye through where it is drawn, cast at most
  every 100 ms while the view moves; past the outline, the part hides none). The theme has no colour to spare (every saturated hue
  is the ramp's or the chosen faces' magenta): loads are the ink, fixtures a muted grey, and a
  chosen load row's arrows, or a chosen fixed or roller row's cones, take the chosen magenta.
  Every other kind is one row of a table (`MARKER_KINDS` in `glb/feaMarkers.js`), drawn only where
  the analysis lists it (`markers`) and the study records it, each solid and ghosted as above, in
  the ink (what drives the part) or the muted grey (what holds it or takes from it), never a hue of
  its own, and labelled past its free end as a load is: a **body load** (gravity, an acceleration),
  one arrow through the model's middle along it, "1 g down"; a **shaker**, a double arrow standing
  off each fixed face along the shake, "shaken 1 g along Z" ("shaken at random", "a shock"); a fixed
  **temperature**, grey dots on its faces, "25 °C"; **heat**, wavy arrows into its faces, "15 W";
  the **air**, grey strokes rising off its faces, "air 25 °C"; a **drop**, an arrow on the face that
  lands, the way it falls, "1 m drop"; a flow's **inlet** and grey **outlet**, an arrow into and out
  of the side of the part's box each names, "0.5 m/s" and "0 Pa"; a **rigid plane** (a contact
  floor, or a drop impact's floor through the lowest point along the fall), one see-through grey
  quad, unlabelled; a **crack front** (fracture), an ink dot at each station along it where its K was
  read (`extras.crack.front_mm`), unlabelled; a **speaker** (acoustic, a sound source's face), a small
  ink cone on the face opening off it with two rings of sound past it, "2 mm/s"; a part shaken by a
  harmonic result (`from: "harmonic"`) is its own source, its broad faces (each at least a quarter of
  its largest, a held face not) marked so, "vibrating"; a piezo
  **electrode**, an ink plate on its faces with a terminal standing off it, "10 V" or "open"; a
  rotor's **bearings**, two grey races lying on their faces, unlabelled, all one group as Study's
  one Bearings row. Choosing a setup row takes its own markers to the chosen magenta. What you see has
  one gate for them, a checkbox after its controls, titled per analysis (**Loads and fixtures**, **Heat inputs and
  temperatures**, **Shaker and fixtures**, **Flow openings**), its line saying what it draws ("Arrows
  where the study loads the part, cones where it holds it."; "Dots where its temperature is fixed,
  wavy arrows where heat goes in, strokes where air cools it."), on unless the study's `view.show`
  turns both off (it then draws both when turned on); `view.show` leaving one kind off keeps it off
  (`loads` the ink's kinds, `fixtures` the grey's), its labels with it.
- **Clip** cuts a result open, so what is inside a part shows: a cooling channel's walls, a tank's
  floor, a duct's surfaces past its openings, each in the field's colours. It is the Clip every scene has
  (`kit/tools/model-effects/`: its tool, its row and the viewport's cut, `useSceneEffects`), kept as the
  file's view keeps it; it never recolours, so the colour bar reads as before. A pick goes through what the
  cut took away to the face it shows, and a label whose marker acts there (`face`, else its free end) is left
  out: both read the plane in force from the runtime (`activeClipPlanes`). A result has no X-ray: X-ray,
  Hidden line and Wireframe are drawn from edges, and a result has none.
- **The choices are the file's view**: one renderer slice (`fea`: the field, the deformation, the
  load, the threshold, the preset and the markers' gate, and once chosen the mode, the frame and
  the sigma level; a result with no series writes the slice it always did), written against the
  result's fields, scale and view, so a re-solved result opens at its own defaults.

## Position and references

**Position** is a section of the [file sidebar](#the-file-sidebar-and-the-tool-stack), its
tile there under every tool, headed "Position": a STEP's where the file has joints to move, a
robot's where a joint can be driven. Its knobs in the viewport are Select's, while Select's
filter ticks Position, and only while the parts are where the pose puts them: over an explosion
Select draws no knobs (the section's controls stay, and using them takes Explode off). Its
heading holds **Reset position** before its X, idle while the joints are at their default. Its
first row is the pose, a dropdown the panel's width (`KinematicsPoseRow`, `data-pose-row`):
**Default**, which puts the joints back, then the named poses, and Custom while the joints are
set by hand. No divider under the pose row and no Reset footer.
Each joint's label sits tight above its
slider in the flexible left column, with a compact value field (24px tall, about
five characters wide, tabular figures; degrees read "90.0°") in the right column
of the same row; joint rows are 4px apart. Long labels truncate with a full-name
hint and never take the slider's width. Every slider in the viewer is shadcn's slider
(`primitives/slider.jsx`), with a 12px thumb (16px on a phone, in a 36px band) and a track a
shade darker than muted, for these dense, see-through panels: a row sizes and places it, never
restyles its track or thumb — but for a joint's, which has no fill (a joint's zero is mostly
mid-range, so a bar from the left end means nothing). Slider thumbs are named after their
joint, and every slider reports its value at its step's precision (never float
noise). Writes pose the model at once.

Position persists across tools, and across an update of the model whose joints and
named poses are unchanged, the named pose chosen included; an update that changed them
starts the pose at the new defaults, never fitting the old values onto other joints.
Default restores the authored
values (an SRDF's home included), stops motion and hands control back to
Position. Using Position takes Explode off, and taking up Explode puts the pose back to its
default ([one motion at a time](#tools-and-lifecycle)); while the model is exploded there are no
knobs. Preview leaves the tools view's pose as it is and never shows it: it opens on the model
at rest, and a pose set there is its own (see [Preview](#camera-animation-and-preview)). Kinematics, named poses and
animation are separate capabilities; the absence of one never leaves empty
controls for another.

What is picked is [Quick Edit](#quick-edit)'s chips, and a chip's card is what a person
reads of it (`kit/tools/quick-edit/ReferenceChips.jsx`). A component or subassembly is a chip
of its own; faces, edges and solids are a chip for each kind on each part — "base · face 3"
alone, "base · 6 faces" for several, however they were picked — so a large selection stays a
few chips. A chip names its reference: its own label when it has one (a part's or
subassembly's name, a named face), otherwise its part and kind ("base · face 3") — never the
raw id, which its card shows under the name. In a STEP the card's rows are the reference's key
measurements, nothing else: a face's area, and a round face's diameter and radius (a torus's
two radii); an edge's length, or a round one's diameter, radius and circumference or arc
length, with an arc's sweep; a part's size and volume; a subassembly's part count, size and
volume; a run on one part, one row each. Its rows are the UI font at `text-tiny`, numbers in
tabular figures — no monospace. A click on a chip copies its references, each naming its file
by absolute path; resting on it lights its picks; its X drops them.

Viewport picks reach individual faces and edges. In an assembly, faces and edges load per part, when first
needed: under a face or edge filter, a press on a part whose faces are not
loaded loads that part alone and then picks what is under the pointer — one
press, with "Loading…" in the model tree's heading meanwhile. Until
then, hovering such a part lights the whole part.
Shift-click adds to a selection in the viewport; Shift, Ctrl or Cmd does in a
tree (robots select several links this way). Double-click, or a row's Isolate,
isolates a component or subassembly; double-click on empty space leaves
isolation, as do the isolation bar's Exit and the lit Isolate. Only topology that
cannot be isolated copies on double-click, and it stays selected.

## Quick Edit

Quick Edit is a person's note to their agent about the file on screen, and the
one way the viewer hands it over: a box at the viewport's top-right, 8px in, on the
floating surface. It is there only while it has something to carry or a note to keep:
nothing stands in for it otherwise, not even a button. Only a view whose picks and
annotations a note can carry has it (a STEP's, a robot's); a compact host gets none, and
Preview puts it away with the tools. While the view loads it is out of sight, its note
and its state kept. It is essential, so no setting turns it off.

The sidebar and Quick Edit keep their corners, 8px in, unless one would reach under the tool
strip or its tool's row: then it starts 8px below them instead (measured, `--cad-sidebar-top` and
`--cad-top-right-top`), so the strip is never covered. They may overlap each other.

On a phone Quick Edit is a bottom sheet, shadcn's drawer as it ships (`primitives/drawer.jsx`,
vaul): full width, non-modal, never swiped away (its X clears it). It opens at a peek of its
handle, header (its title, what goes with the note, the X) and chips, and a pick never brings up
the keyboard. A swipe up, or a tap on its way in (below), takes it to its open stop,
62% of the screen, its note filling what the header and buttons leave, the keyboard in it; a
swipe down takes it back to the peek, what is written kept. Peeking, under its chips is its way
in, a field-like button reading "Describe your changes…" with a pen, which opens it so; its title
is the sheet's heading, a step up the scale. A tap on a chip opens its card (above the chip,
inside the screen) and copies nothing: the card's title copies. Beside the box, on a desktop, a
card opens to the box's left and a click on the chip copies it. It has no grip there.

The box opens 15rem wide, capped to its column, its note growing with what is written up to 10rem. Its
bottom-left corner — the grip every resizable box over the viewport has
(`kit/tools/ResizeGrip.jsx`) — drags it wider to the left and its note taller, for as long as the
box is open: once it closes, however it closes, the next box opens at 15rem again, and
so does another file's. A drag keeps the box at the corner, a frame at a time and
never eased, and renders nothing: the size is written to the box itself, so nothing
else in the viewer redraws under the pointer. Its header is the title, one step up
the type scale ("Quick Edit"); then what goes with the note, in muted text: **N
ref(s)**, the selection counted one by one (a reference naming several picks counts
each; hovering lists their ids, one a line), and **annotation** while there are annotations;
then an X. The file always goes and is not named. Under the header, the note
("Describe your changes"), its border blue while it has the keyboard, and the
buttons at its bottom-right.

While the note is empty the box follows what it would carry: it opens when something
is picked, annotated or measured, and closes when that goes. Every chip leads with its
icon — the Annotation chip's pen, a measurement's ruler in its colour, a reference's pick glyph
(a part's cube, a face, an edge, a vertex) — then its words, and they stand in the order
they came, whatever their kind. A chip's copy pasted into the note is a pill there,
drawn as the chip is, 20px like the note's lines so it sits in its rows without spacing
them out. A click on a pill selects it whole, highlighted in the selection's colour, so
Backspace, Delete or typing replaces it as it would selected text. Its chips are
**Annotation** (its X clears the ink), each measurement (the ruler in its colour and its
reading, with a details card and an X to remove it), then the selection. Annotation and
measurement chips do not copy references or write files. Copy Prompt, Queue and Send
include their data in the snapshot packet; only selection chips copy individual references. A written note keeps it open whatever
is picked, even with nothing picked or annotated, until the X. The X clears everything:
the note, the selection (as a press on the model's background does), the annotations and the
measurements, so the box goes. A note that has gone (Copy Prompt, Queue, Send) clears the same way.
Escape in an empty box is the viewer's Escape (clearing the selection, and so the box);
in a box with a note it only hands the keyboard back to the model.

The person's picks put the keyboard in the note, each one (a pick right after their
primary press in this view), and so does a first annotation stroke once the pen lifts. A
selection an agent or host makes through the live controller (`select`) opens it without
taking the keyboard.

The buttons, left to right, are only those the host can carry out, and the rightmost
is the primary one, which Enter presses (Shift+Enter is a new line). They are the
`Button` primitive in its own shape — 28px squares with its rounded corners, each an
icon with a name and a hint — and every one is solid: the primary in the `default`
variant, the others in `secondary`. Where Copy Prompt is the only one (a host that
takes no message, as the web), it is a button in words, "Copy Prompt" with its icon
first. While there is no note they are disabled, dimmed but still drawn:

- **Copy Prompt** (copy icon), always. It copies the note as text: its references
  spelled as copied references are, and its files by the paths they were saved at,
  since text carries no file.
- **Queue** (list-plus icon), where the destination is a composer: the note goes
  into the context of the person's next message.
- **Send** (up arrow), where the host can post a message: the note goes now, as the
  person's message.

Every prompt captures the current view and the recorded views with remaining ink.
If the current view matches a recorded view, its exact current framing replaces
that entry for this export; otherwise a `current view` job is appended. Text and
selection alone also capture the current view. The packet stores shared input,
annotation and measurements once, with a `jobs` list of view states.
At Copy, Queue or Send, packets up to 1024 bytes of compact UTF-8 JSON are included
in the prompt as JSON. Larger packets are written to system temporary storage as
one `.snapshot.json` and named by path. Drawing, selecting and typing write nothing.
Captured 3D views preserve projection and lens. No PNG is rendered or attached.
To render inline JSON, the receiving agent saves it to a temporary file first,
then runs `cadgen snapshot --job <file>`.


Queue and Send clear the note and what it carries, and so close the box, once the
note has gone. Copy Prompt keeps it all, since nothing has gone yet: its button
shows a tick for a moment. A failure keeps the note and says why in the box. The message is
one format, sent, queued or copied: what the person wrote; then `File: <path>`; then
`References:` and one reference per line; then each file that travels as a file by its
label and path — `Snapshot (cadgen snapshot --job):` — or the compact object under
`Snapshot JSON (cadgen snapshot --job):`.

## Camera, animation and Preview

Cube face, edge and corner clicks turn the view and keep pan and zoom; dragging
the cube orbits. Reloading the page restores the camera the file on screen was left
at, and its Display settings, Explode/Clip, the pose, hidden and isolated parts and
the tree's expansion come back with it. Only the model on screen keeps that view:
leaving it — for another file or the home — drops it, so opening a file,
for the first time or again, fits it at the defaults. An update of the model on
screen keeps its Display settings, Explode/Clip, hidden and isolated parts and its
tree, and the pose while its joints are unchanged. The tool, the selection and
measurements never come back — every open starts in the default tool with nothing
selected.

Zoom to Fit recenters and frames the whole original model at the current angle;
Zoom to Selection frames the selection and is unavailable without one. Both are
STEP context-menu items; the live `resetCamera` command takes the same fit path.

**Preview** (`previewing` in code) is available for every 3D file, animated
or not, and for nothing else: a renderer declares it (`useRendererShell`'s `previewable`: STEP,
GLB, STL/3MF, URDF/SRDF/SDF), and a view whose renderer does not (a DXF, 2D) has no Preview
button, not a disabled one, and never enters it, whatever asks. It is the shell's own state;
hosts neither start nor observe it. Its button is a play triangle ("Preview"), at the navbar's
right end after Display (the renderer's `navbarSlot`; a host with no navbar has both end the
strip). A press covers the view at once
("Preparing preview…", in the scene's backdrop colour) and enters Preview under the cover,
which lifts once Preview's view has presented its first frame, no finer detail is on its way
(the quality is neither preview nor refining) and the studio frame's picture has converged
(every sample drawn: the viewport's `pictureProgress`) — at least 700ms; at five seconds it stops
waiting for detail and lifts on the picture converged, a second later at the latest — fading from
the finished picture (`kit/shell/previewCover.js`). A view the shell set moving, Orbit
on or a routine playing, has nothing to wait for; detail that lands starts the picture again and
is waited for, never read as motion. Preview's scene takes finer detail in grouped steps,
after a quiet moment or every second while it streams (`step/workbench/settledValue.js`), so a
burst of batches restarts the picture once or twice, not per batch. The navbar stays, so its menu and the explorer
still lead to other files; the tool strip, its sub-toolbar, the tool stack and their resize grips, Quick
Edit, joint handles, cube and context menu are gone (`PreviewChrome`, hidden and inert).

Its controls are always there. At the navbar's right end, in Display's and Preview's place:
**Preview settings** (a sliders icon, pressed while its panel is open) and the way out, an X
(**Exit preview**), their hints below them (a host with no navbar has them at the view's
top-right, `PreviewChrome`'s `end`, tiles with no surface under them). Under them, docked at the view's right edge, the settings panel
(`kit/shell/PreviewSettings.jsx`), closed each time Preview opens and put away by its button
or its own X: **Orbit** — its heading's checkbox turns the camera about the model, off every
time Preview opens, and its **Speed** is a dropdown of speeds — then Render's own settings
page (see [Display settings](#display-settings-and-section-primitives)). At the top-left, the
file sidebar offers its **Position** and **Animation** alone, their tiles bare: Preview's own
pose and routine. Escape leaves Preview too, once an open dropdown has closed. Explode and
Clip are the tools view's alone. Nothing sits under the model, nor at the bottom centre.

**Preview is drawn in Render**, whatever the file's display mode: it is a view of its own
over the tools view, drawing the file's Render settings, and the file's own mode and its
settings are left as they are. The tools view never draws Render: no file's mode is Render,
a live `setDisplaySettings` refuses it as it refuses any mode it does not know, and a saved view
left in it reads as the defaults. Render settings edited in Preview are the file's Render settings;
leaving returns the tools view to the file's mode.

**Routines** play from the file sidebar's **Animation** section, in the tools view and the
Preview alike (`kit/tools/playbar/AnimationSection.jsx`): its heading holds **Reset animation**,
which stops the routine and puts the model at rest, disabled while it is; its body is the
routine in hand, a dropdown of the routines where there are two or more, then **Play** or
**Pause**, the scrubber (`AnimationTimeControl`) and **Playback settings** (a cog: the routine's
Speed, a submenu, then Loop and Autoplay). In the tools view a routine is a motion as a pose is
(see [one motion at a time](#tools-and-lifecycle)): paused, its frame stays on the model. A
routine opens at rest (a STEP's does not own the pose: `restingAnimationState`,
`step/workbench/motionRestore.js`). Each view's routine is its own: entering Preview sets the
tools view's untouched and starts its own at rest, playing only under Autoplay (off by default);
leaving throws Preview's away, and the tools view's is as it was left. An update of the model that leaves its routines as they were neither stops nor rewinds
one that is playing; a changed routine starts at rest. Speed and Loop are the file's, one set,
chosen in Playback settings and kept in its view once chosen — until then the routine's own
apply. Orbit's speed (1×) and Autoplay are the file's too, remembered between leaving and
re-entering Preview and across a reload of the tab; whether it orbits is not kept. Another
file has its own, and a file the tab left starts at the defaults again. Nothing of the
routine — which one, its time, whether it plays — is saved. Orbit is not an animation
setting.

**Preview and the tools view are two states.** Entering Preview leaves the tools view's
state exactly as it is — the tool in hand and its sub-toolbar, the Position pose, the routine,
the selection, hidden and isolated parts, Explode and Clip, Measure's results, the annotations,
the camera — and Preview starts clean, from the model as authored: at its opening pose,
every part shown, nothing isolated, picked, hovered, measured, exploded or clipped, its own
camera fitted at the default angle and still, its routine at rest. Leaving it throws away what
was done there — its camera, its pose, its routine — and the tools view comes back exactly as
it was, in the file's display mode, its camera in the projection and lens the Display settings
now hold. Nothing of the tools view is reset to make room for Preview and nothing of the
Preview's is kept: the next one starts clean again. Preview holds this by being a view of its
own (`kit/shell/PreviewView.jsx`): its own viewport, scene, camera, pose and routine, mounted
over the tools view's while it is up and unmounted as it closes, sharing only the page's GPU
device. The tools view's viewport stays mounted throughout and is never told: it draws nothing
while covered and is uncovered with its own last frame. What is not either state's is the file's settings, shared by
both and kept: its Display settings (an edit in Preview's Render settings is the file's
Render settings), Orbit's speed, Autoplay, Speed and Loop.

**Two views, two ways of drawing.** The tools view is drawn for working on the
model: the scene quality its settings resolve to, and a lower pixel ratio while
the camera moves so a gesture stays responsive. Preview's view is drawn for looking at
it, in Render (`kit/viewport/previewViewScene.js`): one scene-quality tier up (Interactive to
Standard, Standard to High — a higher idle pixel ratio, and at High larger shadow and
environment maps, at the same meshes), its full pixel ratio kept while it orbits, and nothing
of the tools view's (no picking, overlays, cube or tool effects). Neither changes a Display
setting. Render's studio code and environment are prepared a moment after a model is on screen
(`useRendererShell`'s `previewPrepare`), into the GPU device's cache Preview draws from, so
entering Preview has less to do — on a GPU. On a software renderer (SwiftShader, llvmpipe:
the viewport's `softwareRendering`), where that compile would hold the page for seconds unasked,
nothing is prepared ahead: Preview prepares as it is entered, under its cover.

## Keyboard

Escape and Copy belong to one viewer: the one with focus, or the one last
pressed in while focus is on the page. Editable targets keep their own keys.

- **Escape**, innermost first: an open popup in this viewer (a menu, the app menu
  included, a Select, a color picker, Display, the explorer) closes itself; then Preview closes;
  then Annotate's canvas spends its own Escape; then the selected ink; then an unfinished
  measurement; then the tool in hand, any but Select, which goes down and takes Select up, what
  it set kept; then the renderer's own (STEP: the selection, then isolation; robots: the
  selection). The file sidebar and the tool stack's panels are
  never Escape's to close.
- **The file sidebar's grip**, and a resizable panel's (its bottom-right corner), is a
  separator in the tab order: Left/Right nudge its width and Up/Down its cap by 16px, and Home and
  End take both to their bounds.
- **Copy** (⌘C or Ctrl+C, and Ctrl+Insert) copies the view with its annotations
  while Annotate is up, otherwise the selection's references — unless a text field
  has focus or text is selected.
- **Quick Edit's box** keeps its own keys: Enter presses the primary button and
  Shift+Enter is a new line. Escape hands the keyboard back to the view and keeps
  a note; in an empty box it closes the box and is also the viewer's own Escape
  (it clears the selection). ⌘C or Ctrl+C with none of its text selected is the
  viewer's copy.
- **Arrow keys and WASD** orbit the viewer that has focus or the pointer over
  it, never every mounted viewport; they do nothing in Preview or with a
  modifier held.

## Tooltips and feedback

Every hint is a `TooltipHint`: compact text, one surface and arrow, a 400ms
delay. No native `title` anywhere in chrome. Prefer one or two words; show a
full technical name only when it is truncated (`overflowOnly`). Quick Edit's buttons, the
strip's buttons (Display and Preview among them), the navbar's right-hand controls (the
update, an alert's icon, Full size), Preview's corner (Preview settings, Exit preview) and the
Animation section's Reset are hinted by name — the strip's hints above their
buttons, the others' below; there is no hint on the navbar's left (the logo,
the file's name and the ⋯ say what they are), on Display's settings button, Playback settings, an X,
the transport (play, pause, the scrubber), annotation tools or labelled text
buttons (Quick Edit's alone say what they do). A disabled, selected or expanded control has none; pressing or leaving cancels a
pending one. A hint appears on focus only for keyboard navigation (a Tab), never
when a closing menu hands focus back.

The viewer shows no toasts or notifications: copy, snapshot and prompt actions
complete silently, the Copy and Quick Edit buttons showing a tick for a moment.
Progress stays in the viewport; a failed action is the
viewport's alert card, whose **Retry** reloads the file and whose **Report Issue**,
where the host has a tracker, opens a new issue titled "Issue: ", labelled `bug`, filled
in from the card. Its **Details** open into a box that scrolls, with a copy icon at the
box's top-right corner, hinted **Copy**: it copies all of the details and shows a tick for a
moment, or, where the clipboard refuses, a line under the box saying so. Errors handed to
the host's `onError` are the host's to show. A card the
model survives (a failed update, a warning beside the model) has an X, **Dismiss**: it puts
the card away for as long as that alert stands, and its icon, first of the navbar's
right-hand controls after the update button, brings it back. The dismissal goes once the alert changes or clears, or
another file opens; with the card back, so does the icon. Preview has no navbar, and so no
icon.

## Verification

Verify state transitions, touch cancellation, keyboard operation, nested popup
dismissal, feature availability, narrow panels and empty or error states.
Camera and kept-tool tests exercise real transitions, not class names. Do not
keep tests for discarded layouts: replace their assertions with coverage of this
contract. `src/designSystem.test.js` holds chrome to the type scale and the one
breakpoint. The core settings semantics are in
[render-mode.md](render-mode.md); update scheduling is in
[view-updates.md](view-updates.md).
