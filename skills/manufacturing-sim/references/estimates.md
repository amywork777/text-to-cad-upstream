# Estimates: the processes not simulated yet

Hand methods for the processes cadgen does not simulate in this version. Each is an **estimate**:
say so every time you quote one, with its assumptions and its source, and never present it as a
simulation. Where `$fea` simulates part of the question, the section says which part and how to set
the study up; say which part that answers, and that the rest is an estimate.

Work in the units each formula gives; restate the result in the user's.

## Injection moulding

Not in this version: the fill, pack and warp of a moulded part.

- **Cooling time** of a wall of thickness s (the part's thickest wall sets the cycle), cooled from
  both sides, until its middle reaches the ejection temperature [1]:

  t_c = (s² / (π² α)) ln((4/π) (T_melt - T_mould) / (T_eject - T_mould))

  with α the plastic's thermal diffusivity (about 0.08-0.12 mm²/s for most unfilled plastics; the
  grade's datasheet gives k, ρ and c, α = k / (ρ c)) and the three temperatures from the grade's
  processing sheet. A 2 mm ABS wall, α = 0.1 mm²/s, melt 240 °C, mould 60 °C, ejection 90 °C: about
  8 s. It grows with the square of the wall: a 4 mm wall takes four times as long.
- **Sink risk.** A rib or boss thicker than about 0.5-0.6 of the wall it joins leaves a sink mark
  opposite it; a wall that varies more than about 25 % warps and sinks where it is thick [1]. These
  are the moulders' rules of thumb: `$dfm` reviews a part against them with measurements, so send a
  full review there.
- **Fill.** Whether a long thin wall fills depends on the grade's flow length to thickness ratio
  (its datasheet's spiral flow, typically 100-250 for a 1-2 mm wall); a flow path longer than that
  ratio times the wall is a short-shot risk. An estimate; the moulder's flow simulation answers it.
- **Warp.** No honest hand method: say it is not in this version, and name the causes to look at
  (uneven walls, uneven cooling, a fibre-filled grade's orientation).

## Heat treatment and quenching

Runs today as `heat_treatment` ([heat-treatment.md](heat-treatment.md)); this estimate stays its hand
check.

Not in this version: phase change, distortion and hardness after a quench.

- **How fast it cools** runs today: `$fea`'s `thermal_transient` (heat over time) with the part at
  its austenitising or solution temperature (`initial_C`) and a `convection` entry on every face at
  the quench's coefficient and temperature. Coefficients are ranges, from still air about 10, forced
  air 25-100, oil a few hundred to about 2000, to water and brine a few thousand W/(m² K) and more,
  depending on agitation and the vapour blanket [2]; the steel's own properties come from
  `$fea`'s material table. Report the time the core and the surface take to pass the temperatures
  that matter for the steel (for example 800 to 500 °C), and say the coefficient is a range.
- **Distortion and residual stress.** `$fea`'s `thermal_stress` gives the elastic stress of one
  temperature field, which is not a quench's: a quench yields the part and transforms its
  structure. No honest number: say it is not in this version. Uneven sections and one-sided
  cooling are what distort.
- **Hardness.** From the steel's own Jominy curve and the cooling rate at the point (the cooling
  above): a lookup, not a simulation, and only with the grade's Jominy data from the user [2].

## 3D printing

Not in this version: the layer-by-layer build, warp, curl and residual stress. Printability (walls,
overhangs, supports, orientation) is `$dfam-check`'s.

- **FDM warp.** Each layer shrinks by the thermal strain α (T_glass - T_bed) as it cools to the bed,
  and a long flat part curls up at its ends: about 0.6 % for ABS (α ≈ 90 × 10⁻⁶ /K, 100 to 30 °C),
  about 0.3 % for PLA (α ≈ 70 × 10⁻⁶ /K, 60 to 20 °C), the grade's α from its datasheet [3]. The
  strain over the part's length is the shrinkage the bed adhesion must hold; a part longer than
  about 100 mm in ABS without an enclosure is a known curl risk. An estimate, not a deflection.
- **Resin (SLA/DLP).** Volumetric shrinkage on curing is a few percent; thin flat areas and
  overhangs curl. Use the resin's datasheet shrinkage; no hand method gives a warp.
- **SLS/MJF.** Thick flat areas and sudden thickness changes warp as the powder bed cools; the
  printer's design guide gives its limits. `$dfam-check` measures them.
- **Metal powder bed.** Residual stress reaches the order of the alloy's yield as built, which is
  why parts are stress-relieved on the plate before removal [3]; tall thin features and large flat
  areas distort. No hand number beyond that: say it is not in this version.

## CNC machining

Not in this version: the cut itself, tool wear, and chatter as a simulation.

- **A thin wall's deflection under the cutter** runs today in `$fea` as `static`: the faces the vise
  or fixture holds `fixed`, and the cutting force as a `force` on the face the cutter is on. The
  tangential force is about k_c × a_p × f_z (specific cutting force × axial depth × feed per tooth)
  for one engaged tooth, with k_c about 500-900 N/mm² for aluminium alloys and 1500-2500 for steels
  and stainless (it rises as the chip thins) [4]: an estimate of the load, said as one. The wall's
  deflection there is what is cut out of tolerance.
- **The clamp's deflection** the same way: the clamp's force on its faces, the opposite faces
  `fixed` (a `roller` where the part can slide).
- **Chatter-free spindle speeds.** The part's (or the tool's) first natural frequency f_n runs
  today in `$fea` as `modal` with the fixture held; a tap test measures it better. Chatter is least
  where the tooth-passing frequency is f_n divided by a whole number: spindle speeds
  n = 60 f_n / (z (k + 1)) rpm, z teeth, k = 0, 1, 2 ... [4]. These are the centres of the stable
  lobes; how deep you can cut there needs the cutting coefficients and the damping: an estimate.

## Sheet metal

Not in this version: the bend, the draw, and springback as a simulation. Bend rules (radii,
reliefs, flange lengths, hole distances) are `$dfm`'s.

- **Springback** of an air bend, from the inside radius R_i before release to R_f after [5]:

  R_i / R_f = 4 (R_i Y / (E t))³ - 3 (R_i Y / (E t)) + 1

  with Y the yield strength, E the modulus and t the thickness; the bend angle opens by the same
  ratio, θ_f = θ_i (R_i / R_f) for the bend's arc. A 1.5 mm 5052-H32 sheet (Y 193 MPa, E 70 GPa) bent
  to R_i = 3 mm opens by about 2 %; a stainless sheet at a large radius springs back far more. Over-bend
  by the ratio.
- **Cracking at a tight bend.** The minimum bend radius for a sheet whose tensile reduction of area
  is r percent is R_min / t = 50 / r - 1 [5]; a tighter bend, or one along the rolling direction in
  a cold-worked temper, cracks on the outside. The supplier's bend table overrides it.
- **Draw thinning and the draw ratio.** A cup draws in one stroke while the blank diameter over the
  punch diameter (the draw ratio) stays under the limiting draw ratio, about 1.8-2.2 for most
  steels and aluminium alloys [5]; past it the wall tears near the punch radius, where it thins
  most (10-25 % thinning is usual there). An estimate; redraws are needed beyond it.

## Welding

Not in this version: the weld's heat, its distortion and its residual stress as a simulation.

- **Transverse shrinkage** of a butt weld: about 0.2 × (weld cross-sectional area / plate thickness)
  + 0.05 × root opening [6].
- **Longitudinal shrinkage** along the weld is much smaller, but bows a long member welded off its
  neutral axis [6]: balance the welds about it.
- **Angular distortion** of a fillet or one-sided butt weld grows with the weld size over the
  plate thickness; balance the welds about the neutral axis, preset the parts against it, or clamp
  [6]. No reliable single number by hand.
- **Residual stress** in and beside the weld reaches the order of the weaker metal's yield strength
  [6]: assume yield-level tension along the weld in a fatigue or crack check. `$fea`'s `fracture`
  and `fatigue` take it as a stress to add; say it is an assumed value.

## Reflow soldering

Not in this version: solder flow, wetting, voids and tombstoning.

- **The parts' temperatures through the profile** run today in `$fea` as `thermal_transient`: the
  board and its parts (an assembly, each part its material), `initial_C` the room's, and a
  `convection` entry on every outer face whose `ambient_C` follows the oven's profile as a `history`
  (the factor times a base temperature), with h about 20-60 W/(m² K) in a forced-convection oven
  (an estimate: the oven's own data is better). A profile per J-STD-020 for lead-free solder [7]:
  preheat to 150-200 °C over 60-120 s, time above the 217 °C liquidus 60-150 s, a 245-260 °C peak.
- Report each part's lowest peak (a big connector or a heavy ground plane lags) against the 217 °C
  liquidus and the time it spends above it, and each part's highest against its own rating (the
  part's moisture sensitivity level and peak in its datasheet). The profile is the user's or the
  standard's: say which.

## Forging, extrusion and deep drawing

Not in this version: die fill, the flow of the metal, and laps as a simulation.

- **Upsetting a cylinder** (open die, the slab method with Coulomb friction μ) [5]:
  F = Y_f π r² (1 + 2 μ r / (3 h)), with r and h the radius and height at the end of the stroke and
  Y_f the flow stress at that strain and temperature (much below the yield for hot forging: from
  the alloy's hot-working data). μ is about 0.1 lubricated cold, 0.2 or more hot.
- **Closed-die forging:** F = K_p Y_f A, with A the projected area of the forging and its flash and
  K_p about 3-5 for simple shapes, 5-8 for simple shapes with flash and 8-12 for complex ones [5].
- **Extrusion pressure** (Johnson's formula) [5]: p = Y_avg (a + b ln R), R the extrusion ratio
  (billet area over extrudate area), a ≈ 0.8, b ≈ 1.2-1.5; the ram force is p × billet area, plus
  the billet's friction on the container in direct extrusion.
- **Deep drawing force** (the maximum punch force) [5]: F = π D_p t UTS (D_0 / D_p - 0.7), D_p the
  punch diameter, D_0 the blank's, t the thickness.

## Sources

1. Menges, Michaeli and Mohren, How to Make Injection Molds, 3rd ed. (Hanser, 2001), chapter on
   cooling, for the cooling time; Malloy, Plastic Part Design for Injection Molding (Hanser, 2010)
   for the rib and wall ratios.
2. Totten (ed.), Steel Heat Treatment Handbook (CRC, 2006): quenchants' heat transfer coefficients,
   Jominy hardenability.
3. Gibson, Rosen and Stucker, Additive Manufacturing Technologies, 2nd ed. (Springer, 2015): warp,
   curl and residual stress by process; the polymers' expansion coefficients from their datasheets.
4. Altintas, Manufacturing Automation, 2nd ed. (Cambridge, 2012): cutting forces and stability
   lobes; Sandvik Coromant's handbook for specific cutting force k_c by material group.
5. Kalpakjian and Schmid, Manufacturing Engineering and Technology (Pearson): springback, minimum
   bend radius, limiting draw ratio, forging (slab method and K_p), extrusion and deep-drawing
   forces.
6. Lincoln Electric, The Procedure Handbook of Arc Welding, 14th ed. (2000), section on controlling
   distortion: transverse and longitudinal shrinkage, angular distortion, residual stress.
7. IPC/JEDEC J-STD-020: the lead-free reflow profile and peak temperatures.
