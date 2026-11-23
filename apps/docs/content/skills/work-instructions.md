---
title: work-instructions
description: The work-instructions skill writes step-by-step instructions for building one assembly as a PDF, a picture guide by default or a shop work instruction with sign-offs.
---

The `work-instructions` skill writes instructions for building one assembly, as one PDF. By default it is a picture guide anyone can follow, like a furniture manual: what you need, then one big picture and one short sentence a step, with the new parts highlighted and an arrow where they go. Beside the PDF it writes a page to open in any browser, where you turn the model in 3D and step through the build, and the same build as a GLB.

## How it works

`cad.work_instruction` reads the assembly's document, checks every step against it, and writes the PDF. There is no CLI: the script your agent writes is the interface.

For a shop building to company rules it writes a work instruction instead: sign-offs the shop keeps, and torque, bonding and cure values cited to your own process specs.

## Limits

- One assembly per document. Each step is checked against the assembly, so a step that names a part the assembly does not have is refused.
- Process values (torque, cure times) come only from the specs you give it; it does not invent them.
