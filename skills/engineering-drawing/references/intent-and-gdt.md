# Design intent, tolerances and GD&T

A drawing is a contract: what it states is what a shop makes and an inspector
measures. Which dimensions matter, how tightly, and from which faces depends on
how the part is used and how far along it is, and only the person knows that.
So ask before dimensioning, propose what you think matters, and write into the
drawing script only what they confirm.

## The interview

Ask one thing at a time, in plain words with the standard term in brackets.

1. **Stage and use.** Is this a concept to talk over, a prototype, or for
   production? Who makes it (a machine shop, a 3D printer, a molder)? What does
   the part mount to, what moves against it, what has to fit? Ask whether their
   company has its own drawing format (a profile, below).
2. **Propose what matters, one numbered item at a time,** read off the part:
   - the faces it locates on, the ones it is bolted or clamped down by
     (datums A, B, C)
   - pin and fastener holes (position, to those datums)
   - bores that take a bearing, bushing or pin (a fit: H7 and the like)
   - sealing, sliding and mating faces (flatness, perpendicularity, a finish)
   - what can be loose (the general tolerance covers it)

   Show each one: a picture of the part with that feature marked (below). An
   assembly's part is shown in place, the rest faded (`--focus`).
3. **The person confirms, changes or removes each item.** They may click the
   face they mean in the CAD viewer and paste its reference instead. A standard
   fit (ISO 286) may be suggested by name; a number is never applied without a
   yes.
4. **Write only confirmed values** into the drawing script, as ordinary calls:
   `tol=`, `fit=`, `basic=True` and a `Frame`, `view.datum(...)`,
   `parts.set(...)`. The script is the record of the interview: rerun it after
   a model change and nothing is asked again. Anything not confirmed stays
   blank, and the run reports it.
5. **For an assembly, ask joint by joint how each is held:** a torque, a
   threadlocker grade, a press fit, a bond (adhesive and its cure), a weld,
   tape, rivets, snaps, or nothing at all. Each answer is a flag note
   (`view.flag(..., joint=...)`, [assemblies](assemblies.md)).

### A picture per question

Mark the feature with an annotation and render it with `cadgen snapshot`. An
annotation is JSON in model millimetres: a closed `stroke` round the feature
(points on its edge, x y z triples), and a `text` mark with its number (four
corner points, in the plane the label should face).

```json
{
  "units": "mm",
  "marks": [
    {"id": "bore", "kind": "stroke", "color": "#d9480f", "width": 4, "closed": true,
     "points": [6, 0, 10, 4.24, 4.24, 10, 0, 6, 10, -4.24, 4.24, 10, -6, 0, 10, -4.24, -4.24, 10, 0, -6, 10, 4.24, -4.24, 10]},
    {"id": "label", "kind": "text", "color": "#d9480f", "text": "2", "fontPx": 28,
     "points": [8, 8, 10, 14, 8, 10, 14, 14, 10, 8, 14, 10]}
  ]
}
```

```bash
cadgen snapshot STEP/clevis.step tmp/intent/2-bore.png --camera iso --annotation tmp/intent/2-bore.json
cadgen snapshot STEP/rig.step tmp/intent/3-pin.png --camera iso --focus "#o1.2"
```

Name the pictures by item and show them beside each question.

## Three kinds of dimension

| Kind | Call | Prints | Means |
| --- | --- | --- | --- |
| toleranced | `tol=0.1`, `tol=(0.05, 0.02)`, `fit="H7"`, `limits=(39.98, 40.02)` | `40 ±0.1`, `40 H7`, the two limits | inspect it to this |
| basic | `basic=True` | `40` in a box | the exact target; a GD&T frame bounds the feature |
| reference | `reference=True` | `(40)` | information only, never inspected; an assembly's envelope |

A dimension with none of these is governed by the general tolerance or the
general profile. A basic dimension with no frame on its sheet is reported:
nothing bounds it. `diameter()` and `radius()` take `basic` and `reference`;
`overall(reference=True)` makes both overall sizes reference.

## Frames and datums

```python
from cadgen.eng_drawing import Frame

front.datum("A", (0, -25, 0))                  # the face it bolts down on
top.datum("B", (-40, 0, 10))                   # the edge it is pushed against
top.hole((20, 0, 10), frame=Frame("position", 0.1, ("A", "B"), diameter=True, modifier="M"), key=True)
top.dim((-40, 25, 10), (20, 25, 10), basic=True)   # the hole's true position from B
front.frame((0, -25, 10), Frame("flatness", 0.05)) # a free frame on a surface
```

- `Frame(characteristic, tolerance, datums=(), diameter=False, modifier=None)`.
  Characteristics, in ASME Y14.5-2018's order: `straightness`, `flatness`,
  `circularity`, `cylindricity` (form, no datums); `line_profile`,
  `surface_profile`; `angularity`, `perpendicularity`, `parallelism`
  (orientation, datums required); `position`, `concentricity`, `symmetry`
  (the last two are ISO 1101's; Y14.5-2018 dropped them); `circular_runout`,
  `total_runout` (datums required). `diameter=True` (a cylindrical zone) and
  `modifier="M"` or `"L"` (material condition) only where they apply; anything
  else is refused, with the rule.
- `view.datum(letter, point, offset=None)` stands a datum feature symbol on the
  face through `point`, out by the nearest side of the view. `datum=` on
  `hole`, `slot`, `dim` or `diameter` makes that feature of size the datum.
  Letters I, O and Q are refused, and a letter names one feature per sheet.
- A frame naming a datum no view of its sheet defines is refused.
- `frame=` on a hole, slot or diameter callout hangs the frame under its text;
  on a `dim`, beyond its value. `key=True` marks a key characteristic with the
  profile's boxed letters.
- `Sheet(general_profile=Frame("surface_profile", 0.2, ("A", "B", "C")))` is
  note 1, `UNLESS OTHERWISE SPECIFIED, ALL SURFACES` and the frame: every
  surface the drawing does not control one by one is within that profile.
  Then dimension features with basic dimensions and give the ones that need
  more their own frames.

## Stages

`Sheet(stage=...)` is `"concept"`, `"prototype"` or `"production"`. It prints
in the title block and sets what the completeness report asks a part's sheet
to define:

| | Concept | Prototype | Production |
| --- | --- | --- | --- |
| Tolerance | nothing asked | a general tolerance or general profile | datums, and a general profile or general tolerance |
| Material | nothing asked | the material | the material and its spec, and the finish |
| Key characteristics | none | none | asked whether any feature is one (a note) |
| Title block | CONCEPT, NOT FOR MANUFACTURE | PROTOTYPE | PRODUCTION |

A concept drawing need not be finished: nominal sizes are fine. Keep GD&T off
concept and prototype drawings unless the person asks for it.

## Profiles

A profile is a company's or an industry's conventions, never its numbers:

```python
from cadgen.eng_drawing import AEROSPACE, GENERIC, Profile

Sheet(stage="production", profile=AEROSPACE, company="EXAMPLE AERO CO.",
      fields={"CAGE CODE": "0ABC1", "DISTRIBUTION": "D"},
      material="AL 7075-T7351", spec="AMS 4078", finish="ANODIZE PER MIL-A-8625 TYPE II",
      general_profile=Frame("surface_profile", 0.2, ("A", "B", "C")), general_tolerance="±0.1")
acme = Profile("ACME", "ASME Y14.5-2018", {"TYPE A": "concept", "TYPE B": "prototype", "TYPE C": "production"},
               characteristic_mark="CC")
Sheet(profile=acme, category="TYPE B")          # prints TYPE B, checked as a prototype
```

- `standard` is `"ISO GPS"` (ISO 8015, ISO 2768 or 22081 general tolerances,
  ISO 1101 frames) or `"ASME Y14.5-2018"`. One drawing is read by one
  standard: a general tolerance from the other is refused. The profile writes
  its standard's note; under ISO, `general_tolerance` names a standard and
  class ("ISO 2768-m"); under ASME, it states the values ("±0.1").
- `categories` maps a company's own category names to stages.
- `fields` adds title-block cells, blank until `Sheet(fields=...)` fills them.
- `characteristic_mark` is the boxed letters a key characteristic carries
  ("KC"; AS9103 leaves the symbol to the customer).
- `spec_family` is the specifications to suggest for materials: SAE AMS for
  aerospace, ASTM for general commercial work, EN in Europe. A spec depends on
  the product form (AMS 4027 is 6061-T6 sheet and plate; bar and forgings have
  others), so ask the form before suggesting one.

`GENERIC` follows ISO GPS; `AEROSPACE` follows ASME Y14.5-2018 and adds CAGE
CODE and DISTRIBUTION (the distribution statement's letter; its wording goes in
a note). A company writes its own `Profile` in its project.

With no stage and no profile, the drawing is as it always was: no band on the
title block, nothing asked of it beyond the features it leaves undimensioned.
