# `cadgen.work_instruction` reference

```python
from cadgen.work_instruction import (
    work_instruction, Instruction, Spec, Drawing, Stated,
    Torque, Material, Adhesive, Layup, Cure, Machining,
)
```

## Template

```python
from pathlib import Path

from cadgen.work_instruction import (Adhesive, Cure, Drawing, Instruction, Material, Spec, Stated,
                                     Torque, work_instruction)

# The documents, as the user supplied them: number, title, revision.
FASTENING = Spec("PS-2001", "Threaded fastener installation", revision="D")
BONDING = Spec("PS-3002", "Structural adhesive bonding", revision="B")
DWG = Drawing("DWG-1042", revision="B", title="Bracket assembly")

# Each process record once, every value read from the cited section.
# pot_life is left out: the spec the user gave does not state it, so it prints NOT STATED.
EA9394 = Adhesive("EA 9394 paste adhesive",
                  prep="Solvent wipe with IPA, abrade 180 grit, solvent wipe; bond within 4 h",
                  mix="100:17 parts A:B by weight",
                  cure="5 days at 77 F, or 1 h at 150 F",
                  per=BONDING.at("5.1, Table 2"))
LOCTITE = Material("Loctite 242", per=FASTENING.at("6.3"), note="one drop on the first three engaged threads")


@work_instruction(out="../PDF/bracket_assembly_wi.pdf")
def bracket_assembly_wi():
    wi = Instruction(Path(__file__).parent / "../STEP/bracket_assembly.step",
                     title="BRACKET ASSEMBLY", number="WI-1042", revision="A",
                     part_number="BA-1042", drawing=DWG, author="A. Zhou")
    wi.step("Load the base plate", install=["base_plate"]).instruct(
        "Place the base plate on fixture F-12, datum A down.")
    (wi.step("Bond the bracket to the base plate", install=["bracket"], camera="bottom")
       .bond(EA9394, surfaces=["#o1.2.f5"])
       .instruct("Clamp with two spring clamps; remove squeeze-out before it gels."))
    wi.step("Cure the bond").cure(Cure("Room-temperature cure", cycle="5 days at 77 F",
                                       per=BONDING.at("7.2")))
    (wi.step("Install the pin", install=["pin"])
       # A drawing callout that differs from the general torque table cites the drawing.
       .fasten("MS21042-3 nut", qty=1, torque=Torque(40, 45, "in-lbf", per=DWG.at("note 4")),
               locking=LOCTITE)
       .inspect("Pin height 20 +/- 0.2 mm above the bracket", per=DWG.at("note 2")))
    return wi


if __name__ == "__main__":
    bracket_assembly_wi()
```

## `@work_instruction(out="<path>.pdf")`

Declares the instruction. The function returns an `Instruction`; calling it
writes one PDF at `out` (relative to the script), prints every open item, and
returns `[path]`.

## `Instruction(step_path, *, title, number, revision, ...)`

| Argument | Meaning |
| --- | --- |
| `step_path` | the assembly STEP; a single part is refused |
| `title`, `number`, `revision` | the instruction's own; printed on every page |
| `part_number`, `author` | optional |
| `drawing` | the assembly `Drawing`, listed first under DOCUMENTS |
| `status` | `draft` (default, DRAFT on every page) or `released` (refused while anything is open) |
| `size` | `A4` (default) or `LETTER` |
| `camera` | every picture's camera: `iso` (default), `front`, `back`, `left`, `right`, `top`, `bottom` |
| `pictures` | `False` writes no pictures and needs no browser |

`wi.step(title, *, install=(), camera=None, picture=True)` adds the next step
and returns it. `install` names the parts the step puts in place: a label
(every part carrying it), or an occurrence ref (`#o1.2`; a subassembly ref
installs everything under it). A part is installed by one step only. A step
that installs nothing (a cure, an inspection) still has a picture of what is
installed so far, and none while nothing is.

`wi.open_items()` returns what the run prints: each NOT STATED value, and each
part no step installs.

## Step operations

Each returns the step, so they chain, and prints in the order called.

| Method | Prints | The floor fills in |
| --- | --- | --- |
| `instruct(text)` | the user's words | |
| `fasten(hardware, *, qty=None, torque=None, locking=None, sequence=None)` | hardware, torque (NOT STATED when `None`), threadlocker, tightening sequence | torque wrench ID, cal due |
| `bond(adhesive, *, surfaces=())` | adhesive, prep, mix, pot life, cure | adhesive lot, expiry, mixed at, pot life ends, cure start and end |
| `layup(layup)` | material, ply schedule, debulk | material lot, out-time |
| `cure(cure)` | the cycle | oven or autoclave ID, start, end, chart no. |
| `machine(machining, *, surfaces=())` | operation, tool, speed, feed, coolant | machine ID |
| `apply(material, *, surfaces=())` | a sealant, primer or other consumable and how it goes on | |
| `inspect(text, *, per=None)` | an inspection hold point: the step needs an inspector's stamp | inspector stamp, date |

`bond`, `layup`, `cure` and `machine` take `None` for a record nobody has
stated yet; it prints NOT STATED. `surfaces` are face refs (`#o1.2.f3`, from
`cadgen.read_scene(path).resolve("#o1.2")[0].entities("face")`) marked on the
step's picture; each must be on a part installed by that step or before.

## Sources

Every record and every torque takes `per=`, and nothing else is accepted:

| Source | Prints | For |
| --- | --- | --- |
| `Spec(number, title, revision=).at(section)` | `PS-2001 Rev D §4.2, Table 3` | a rule of the company's process spec |
| `Drawing(number, revision=, title="").at(callout)` | `DWG-1042 Rev B, note 4 (drawing callout)` | a requirement the drawing states, including a deviation from the spec |
| `Stated(by, on=date)` | `stated by A. Zhou, 2026-10-23` | something the user said, and only that |

## Records

A field left out prints NOT STATED if it is required, and nothing if optional.

| Record | Required | Optional |
| --- | --- | --- |
| `Torque(low, high=None, unit, *, per)` | `low` and `unit` (`in-lbf`, `ft-lbf`, `N-m`) | `high` for a range |
| `Adhesive(name, *, prep, mix, pot_life, cure, per)` | `prep`, `mix`, `pot_life`, `cure` | |
| `Layup(name, *, plies, debulk, per)` | `plies` | `debulk` |
| `Cure(name, *, cycle, per)` | `cycle` | |
| `Machining(name, *, tool, speed, feed, coolant, per)` | `tool`, `speed`, `feed` | `coolant` |
| `Material(name, *, per, note)` | | `note` |

Values are text as the document writes them (`"100:17 by weight"`,
`"3000 rpm"`): nothing is parsed or converted. Adhesives, layup materials and
threadlockers are listed under MATERIALS on the cover with lot and expiry
blanks.

## The pictures

One snapshot packet renders every step's picture in one browser. Each shows the
assembly as it stands after the step: parts a later step installs are left out,
parts installed earlier are grey, the step's own parts are tinted blue, and
named surfaces are purple. Every picture shares one camera fitted to the whole
assembly, so a part sits in the same place on every page.

## What the run prints

| Line | Meaning |
| --- | --- |
| `open item: step 2 (bond): pot life not stated` | a value the documents or the user still owe |
| `open item: #o1.4 pin: no step installs it` | a part the order leaves out |
| `wrote <path> (N pages)` | the PDF |
