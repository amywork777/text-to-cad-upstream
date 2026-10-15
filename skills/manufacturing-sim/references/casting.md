# Casting (`casting`)

The metal poured into its mould, from the pour to fully solid: where it freezes last, whether the
feeders reach it, where porosity is likely and whether thin sections freeze before the mould fills.
Lite: read [Limits](#limits) before you report.

## When to use it

- "Will it cast", "where will it shrink or be porous", "is my riser in the right place", "will this
  1 mm frame on a silver pendant fill", "how long until I can knock it out": a sand, investment
  (lost-wax, a jeweller's flask included), permanent-mould or die casting of one part.
- Not for the mould filling itself (the flow front, air entrapment, turbulence), gas porosity,
  hot tears or the grain structure: not in this version.

## The study

```json
{"analysis": "casting", "alloy": "a356", "process": "sand",
 "pour_temperature_C": 720, "mold_temperature_C": 25,
 "feeders": [{"faces": ["#o1.f12"]}, {"faces": ["#o1.f3"], "h_W_m2K": 50}],
 "fill_time_s": 4, "mesh": {"size_mm": 2}}
```

- `alloy` (required): a name from [The alloys](#the-alloys), or one of its plain names (`sterling`,
  `925`, `14k`, `18k`, `bronze`, `brass`, `zamak`, `gray-iron`, `cast-steel`, `316`, ...).
- `process` (required): `sand`, `investment`, `permanent_mold` or `die`
  ([The processes](#the-processes)). It sets the mould's temperature, the pour's superheat and the
  mould's heat transfer coefficient.
- `pour_temperature_C`: the metal's temperature as it goes in; above the liquidus. Default: the
  liquidus plus the process's superheat.
- `mold_temperature_C`: the mould's temperature at the pour (a flask's or a die's preheat); below
  the solidus. Default: the process's.
- `h_W_m2K`: a constant heat transfer coefficient from the metal to the mould, replacing the
  process's mould (a coated die, a chill you have a number for).
- `feeders`: the faces metal feeds from while the casting freezes: the gate, the riser, the sprue's
  contact, by the Viewer's selectors. Each entry takes `faces`, and optionally `h_W_m2K` (its own
  coefficient to the mould temperature; left out, the face is insulated, as a riser's metal sits on
  it) or `held_C` (held at that temperature until the rest is solid, then cooled like the mould: a
  riser that outlasts the casting). A feeder is taken to stay liquid until the casting is solid.
- `fill_time_s`: how long the mould takes to fill. Left out, it is estimated from the mass (see
  [The processes](#the-processes)), and the result says so.
- `duration_s`: how long to follow it. Left out, until every point is solid.
- Shared keys, as in `$fea`'s study file: `mesh` (`size_mm`, `refine`; elements are linear, order 1,
  the only order a casting takes), `output`, `fit` (`iterative`, `defeature`) and `view` (controls,
  presets, sections and show; a casting has no `checks`: its findings are its verdict).
- Not taken: `material` (the metal is the `alloy`), `parts` and `connections` (one part: name it
  with `--occurrence` in a document of several).

## The processes

| `process` | the mould | mould temperature, °C | superheat, °C | heat transfer | fill time estimate |
| --- | --- | --- | --- | --- | --- |
| `sand` | sand, at room temperature | 25 | 100 | the sand heats as it takes heat in: h = e / √(π t), e = 1000 W s^½/(m² K) | 2 s per √kg |
| `investment` | a jeweller's flask or a ceramic shell, preheated | 600 | 100 | as sand, e = 600 W s^½/(m² K) | 2 s per √kg |
| `permanent_mold` | a coated steel or iron gravity die | 300 | 100 | constant, 1000 W/(m² K) | 2 s per √kg |
| `die` | a steel die, high-pressure | 200 | 60 | constant, 5000 W/(m² K) | 0.05 s |

- **The insulating moulds.** A sand or investment mould conducts so poorly that it, not the metal,
  sets the freezing time: its face heats up as it takes heat in, like a semi-infinite body, so its
  coefficient falls as e / √(π t) with e = √(k ρ c) its effusivity, the metal-mould contact taken as
  perfect. This is Chvorinov's own model, and why the freezing time grows with the square of the
  section [14]. Silica sand: k ≈ 0.6 W/(m K), ρ ≈ 1500-1600 kg/m³, c ≈ 1100 J/(kg K), e ≈ 1000 [15].
  Gypsum-bonded investment: k ≈ 0.4, ρ ≈ 1000, c ≈ 900, e ≈ 600: an estimate from plaster's
  properties [15]; give `h_W_m2K` or `mold_temperature_C` where you know better.
- **The investment flask's 600 °C** is a jeweller's (Cooksongold's 600-650 °C for 14k gold [2]); a
  steel shell is preheated hotter and an aluminium one cooler, so for those give
  `mold_temperature_C`. An alloy whose solidus is under the preset's mould temperature (aluminium,
  zinc in a 600 °C flask) is refused until you do.
- **The metal moulds.** A permanent mould's or a die's coefficient is the metal-mould contact's,
  set by the coating and the gap that opens as the casting shrinks: reported values run from a few
  hundred to a few thousand W/(m² K) for coated gravity dies and to tens of thousands in a die
  under pressure [16]. The presets are mid-range values, not measurements; give `h_W_m2K` when the
  foundry has one.
- **Superheat** is the usual 50-150 °C above the liquidus (Cooksongold pours 14k at 930-1020 °C
  against its 870 °C liquidus [2]); the presets take the middle.
- **The fill time estimate** is the form of the foundry's pouring-time rules, t = K √(mass) [17],
  with K = 2 s/√kg for a gravity pour, and a flat 0.05 s for a die: an order of magnitude, labelled
  as an estimate in every result. A jeweller's 10 g pendant reads 0.2 s. Give `fill_time_s` when
  the misrun answer matters.

## The alloys

Room-temperature handbook values, held constant through the run. Latent heats marked * are not
published for the alloy and are the mass-weighted sum of its elements' (CRC [1]): an estimate. A
critical Niyama value is given where one is published; where none is, the result shows where
Niyama is lowest and says no threshold is known.

| `alloy` | name | density, kg/m³ | conductivity, W/(m K) | specific heat, J/(kg K) | latent heat, kJ/kg | liquidus, °C | solidus, °C | critical Niyama, (°C·s)^½/mm | sources |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `sterling-silver-925` | Sterling silver 925 | 10360 | 350 | 246* | 112* | 892 | 810 | none published | [4], [1] |
| `fine-silver` | Fine silver 999 | 10490 | 429 | 235 | 104.6 | 961.8 | 961.8 | none (a pure metal) | [1] |
| `gold-14k-yellow` | 14k yellow gold | 13000 | 66 | 222* | 109* | 870 | 830 | none published | [2], [1], [6b] |
| `gold-18k-yellow` | 18k yellow gold | 15300 | 66 | 174* | 87* | 900 | 860 | none published | [3], [1], [6b] |
| `tin-bronze` | Tin bronze C90500 | 8720 | 74.8 | 376 | 192* | 999 | 854 | none published | [5], [1] |
| `silicon-bronze` | Silicon bronze C87300 | 8360 | 28.3 | 377 | 272* | 916 | 821 | none published | [5], [1] |
| `yellow-brass` | Yellow brass C85400 | 8440 | 88.6 | 377 | 172* | 941 | 927 | none published | [5], [1] |
| `a356` | A356 aluminium | 2670 | 151 | 963 | 490* | 615 | 555 | 0.3 | [6], [1], [12] |
| `a380` | A380 aluminium | 2740 | 96.2 | 963 | 500* | 593 | 538 | none published | [7], [1] |
| `zamak-3` | Zamak 3 | 6600 | 113 | 419 | 120* | 387 | 381 | none published | [7], [1] |
| `grey-iron` | Grey iron (class 30) | 7150 | 46 | 490 | 230 | 1200 | 1140 | none (graphite expansion) | [8] |
| `ductile-iron` | Ductile iron 65-45-12 | 7100 | 36 | 460 | 230 | 1160 | 1120 | none (graphite expansion) | [8] |
| `wcb-steel` | Cast carbon steel WCB | 7850 | 50 | 486 | 247 | 1510 | 1470 | 0.775 | [9], [1], [10] |
| `cf8m-stainless` | CF8M stainless | 8000 | 16.3 | 500 | 280* | 1400 | 1375 | 1.0 | [9], [1], [11] |

- Sterling's conductivity is about 350 W/(m K) by the Wiedemann-Franz law from its electrical
  conductivity; 14k and 18k gold take 66 W/(m K), the nearest measured Au-Ag-Cu alloy's (about
  17k) [6b]. In a small investment casting the flask, not the metal, sets the freezing time, so
  these change it little.
- Fine silver freezes at one temperature; it is solved over a 1 °C range so its enthalpy has a
  slope. Its Niyama value means little: a pure metal shrinks into a pipe or a centreline cavity where
  it freezes last, which the hot spots show.
- The irons' liquidus and solidus are a near-eutectic iron's (carbon equivalent about 4.0) and move
  with its chemistry; their 230 kJ/kg is the value commonly used for cast iron (graphite's share of
  the eutectic makes a mass-weighted sum meaningless). Grey and ductile iron expand as graphite
  forms, which offsets part of their shrinkage: Niyama, a steel criterion, is not a reliable
  indicator for them.
- WCB's freezing range is read from the iron-carbon diagram for 0.25 % carbon; CF8M's is wrought
  316's melting range [9]. Steel's latent heat is iron's own, 247 kJ/kg [1] (published values for
  carbon steels run about 250-275).
- The thresholds: WCB's 0.775 is Niyama's own, 1 (°C·min)^½/cm, in these units [10]; CF8M's 1.0 is
  the value Carlson and Beckermann used for nickel alloys and austenitic stainless steels [11]; A356's
  0.3 is the upper end of the 0.2-0.3 one study found for centrifugally cast A356 [12]. Thresholds
  depend on the alloy and the process and are not established for most alloys [13].

## What comes out

- `part.fea.glb`, coloured by `solidification_time` (s), the time each point is fully solid: the
  last to freeze is red. The other fields: `temperature` and `liquid_fraction` per frame (up to 24,
  from the pour to fully solid; the Viewer's Time scrubber opens on the last frame with liquid),
  `niyama` ((°C·s)^½/mm, at a tenth of the freezing range above the solidus, near the end of
  solidification) and `cooling_rate` (°C/s, there). Nothing deforms.
- Curve `liquid_percent`: the share of the volume still liquid against time (the sidecar's `curves`).
- Summary: `solidification_time_s` and `last_to_freeze_at_mm`, `first_solid_s`, `fully_solid`,
  `alloy`, `process`, `pour_temperature_C`, `mold_temperature_C`, `mould` (in words), `volume_mm3`,
  `mass_g`, `modulus_mm` (V/A of the cooled faces), `hand_check`, `fill_time_s` and
  `fill_time_estimated`, `hot_spots` (each `at_mm`, `freezes_at_s`, `cut_off_at_s`, `volume_mm3`,
  `unfed`), `thinnest_section_mm` and `thinnest_section_solid_s`, `min_niyama`, `niyama_critical`,
  the heat: `heat_to_mould_J`, `heat_from_held_feeders_J`, `heat_released_J` and `energy_balance`
  (their mismatch, a share; the march keeps it at round-off), `steps`, `frames`.
- CLI: "solid in 3.05 min; the last to freeze at [x, y, z] mm", "A356 aluminium poured at 715 °C
  into a sand mould at 25 °C, h falling as it heats (...)", "Chvorinov's rule: 3.09 min for V/A
  5 mm", "1 hot spot; thinnest section 6 mm, solid through at 19.7 s; the mould fills in about
  291 ms (estimated)".

## Findings

| Finding | Severity | What it means | What to do |
| --- | --- | --- | --- |
| `misrun` | error | A section is solid through before the mould has filled (its thickness, place and time): a misrun or cold shut. | Thicken it, gate closer to it, pour hotter or preheat the mould; with an estimated fill time, ask for the real one first. |
| `misrun_risk` | warning | A section freezes within 3 times the fill time: metal stops flowing before it is solid, and the run's instant fill is optimistic. | As for `misrun`. |
| `thinnest_section` | info | No section freezes that soon: the thinnest, its thickness and when it is solid through, against the fill time. | Quote it; it is the user's margin. |
| `shrinkage_hot_spot` | warning | A region that freezes after everything around it, cut off from every feeder while still liquid (its place, the liquid volume cut off, when): shrinkage porosity collects there. With no feeder named, the region that freezes last. | Put a feeder on it (a riser, or the gate), or make the path to the feeder freeze after it: taper the section toward the feeder, thin the hot spot, or chill it. |
| `low_niyama` | warning | Niyama is under the alloy's critical value over a share of the casting (the lowest and where): porosity is likely there. Near a feeder's faces it is left out (the feeder's own). | Read it with the hot spots: the same cures. It marks where, not how much. |
| `niyama_no_threshold` | info | The alloy has no published critical Niyama: the lowest value and where. | Compare the field with a sound casting of the alloy; read the hot spots. |
| `hand_check` | info | Chvorinov's rule for the whole casting's V/A against the simulation's last point. | Quote it as the check. |
| `hand_check_far` | warning | The two are more than 3 times apart. | Check the alloy, process and `h_W_m2K`; a part with one thick section in thin walls freezes later than its average modulus says, which is not an error. |
| `no_feeder` | info | No feeder named: every region that freezes last reads as unfed. | Name the gate or riser faces as `feeders` and solve again. |
| `pure_metal` | info | A pure metal (fine silver): solved over 1 °C; Niyama means little for it. | Read the hot spots. |
| `not_solid` | warning | Not solid at the end (past `duration_s`, or 50 times the hand estimate): times to solid there are lower bounds. | Run longer, or check the inputs. |
| `time_limit` | warning | It stopped at its time limit (twice `fit.seconds`, at least 30 s): nothing after is solved. | A larger `fit.seconds`, or a coarser mesh. |

## Hand checks

- **Chvorinov's rule, an insulating mould.** t = B (V/A)², B = (π/4) (ρ L' / (e ΔT))², with
  L' = L + c (T_pour - T_solidus) (the latent heat and everything above the solidus) and
  ΔT = (T_liquidus + T_solidus)/2 - T_mould [14]. A 15 mm cube of A356 in sand: V/A = 2.5 mm,
  L' = 490 + 0.963 × 160 = 644 kJ/kg, ΔT = 560 °C, B = 7.4 s/mm², t = 46 s; the solver reads
  45.9 s, and 183 s for a 30 mm cube (4.0 times: the square of the modulus). Steel conducts less
  well and reads about 20 % over the rule, which assumes the metal conducts without resistance.
- **A metal mould.** The contact and the metal's own conduction in series:
  t = (ρ L' / ΔT) ((V/A)/h + (V/A)² / (2k)). Between n = 1 (the contact controls, small sections)
  and n = 2 (the metal does). A die casting's skin cools well below the solidus, so the solver reads
  1.5 to 2 times this.
- **Feeders.** A riser feeds a section while it is still liquid: its modulus should be at least
  1.2 times the section's it feeds [18], and its own shrinkage volume more than the casting's
  (a few percent of the casting's volume for most alloys).
- **Thin sections.** A plate of thickness s in an insulating mould freezes in about B (s/2)²; a
  rod of diameter d in about B (d/4)².

## Limits

- The cavity starts full at the pour temperature: filling is not simulated (a thin section far
  from the gate freezes sooner than this says), nor is the metal's flow while it shrinks.
- The mould is a heat transfer coefficient to its temperature on every face (a sand or investment
  mould's falls as it heats), not meshed: a mould's re-entrant corners and thin cores, which heat
  through and slow the freezing beside them, are not seen, and a sand core inside a casting reads
  as cold as its outside.
- Constant properties; the liquid fraction falls straight from liquidus to solidus; one specific
  heat for liquid and solid; no undercooling.
- No gas porosity, hot tears, segregation or microstructure. Niyama marks where shrinkage porosity
  is likely, not how much; its threshold is published for few alloys.
- A named feeder is taken to stay liquid until the casting is solid; whether it does is the riser's
  own sizing ([Hand checks](#hand-checks)).

## When the model is big

Linear tetrahedra only (their lumped heat capacity keeps the enthalpy march monotone). Ladder:
`iterative` (multigrid-preconditioned CG instead of a factor) and `defeature`. The time step adapts
by itself (about a hundred steps from pour to solid). Like every march, it stops at its time limit
(twice `fit.seconds`, at least 30 s) where it has got to, and says so.

## Sources

1. CRC Handbook of Chemistry and Physics: the elements' densities, melting points, specific heats
   and heats of fusion (silver 11.28 kJ/mol, copper 13.26, gold 12.55, zinc 7.068, tin 7.15,
   aluminium 10.71, silicon 50.21, iron 13.81, chromium 21.0, nickel 17.48, molybdenum 37.48,
   manganese 12.91, lead 4.77 kJ/mol).
2. Cooksongold, 14ct AY properties sheet: density 13.0 g/cm³, melting range 830-870 °C, casting
   930-1020 °C, flask 600-650 °C.
3. Rio Grande, 18K yellow gold alloy (604700) tech sheet: density 15.3 g/cm³, solidus-liquidus
   860-900 °C, cast at about 1000 °C.
4. JETS, sterling casting grain (92.5 % silver, 7.5 % copper): solidus 810 °C, liquidus 892 °C,
   10.36 g/cm³.
5. Copper Development Association, cast copper alloy data: C90500, C87300, C85400 (density,
   liquidus, solidus, conductivity, specific heat).
6. ASM Handbook, Vol. 2, and the Aluminum Association: A356.0 (2.67 g/cm³, 555-615 °C, 151 W/(m K)
   in T6, 963 J/(kg K)). 6b. A Au70Ag20Cu10 alloy's conductivity, 66 W/(m K) at 20 °C, and
   resistivity 1.37-1.4 × 10⁻⁷ Ω m (gold alloy data compiled at mfgrobots.com, "Au70Ag20Cu10").
7. NADCA, Product Specification Standards for Die Castings: A380 (2.74 g/cm³, 538-593 °C,
   96.2 W/(m K), 963 J/(kg K)); Zamak 3 (6.6 g/cm³, 381-387 °C, 113 W/(m K), 419 J/(kg K)).
8. ASM Handbook, Vol. 1: grey iron class 30 and ductile iron 65-45-12 (density, conductivity,
   specific heat); their liquidus and solidus for carbon equivalent about 4.0 read from the
   iron-carbon diagram (an estimate).
9. ASM Handbook, Vol. 1: carbon steel and type 316 (density, conductivity, specific heat; 316's
   melting range 1375-1400 °C), for ASTM A216 WCB and A351 CF8M.
10. Niyama, Uchida, Morikawa and Saito, "A method of shrinkage prediction and its application to
    steel casting practice", AFS International Cast Metals Journal 7 (1982) 52-63: about
    1 (°C·min)^½/cm, which is 0.775 (°C·s)^½/mm.
11. Carlson and Beckermann, "Use of the Niyama criterion to predict shrinkage-related leaks in
    high-nickel steel and nickel-based alloy castings", SFSA Technical and Operating Conference
    (2008): 1.0 (°C·s)^½/mm.
12. Bhoraniya, Dharaiya and Sata, "Application of Niyama criterion to predict shrinkage porosity in
    vertical centrifugal casting of ASTM A356 alloy", Int. J. Process Management and Benchmarking
    12 (2022) 395-406: a threshold of 0.20-0.30.
13. Carlson and Beckermann, "Prediction of shrinkage pore volume fraction using a dimensionless
    Niyama criterion", Metallurgical and Materials Transactions A 40 (2009) 163-175.
14. Chvorinov, Giesserei 27 (1940) 177-186; Flemings, Solidification Processing (McGraw-Hill,
    1974), chapter 1: the semi-infinite mould and B = (π/4) (ρ L' / (e ΔT))².
15. Flemings (1974), chapter 1, and Poirier and Geiger, Transport Phenomena in Materials Processing
    (TMS, 1994): silica sand's and plaster's thermal properties.
16. Ho and Pehlke, "Metal-mold interfacial heat transfer", Metallurgical Transactions B 16 (1985)
    585-594 (gravity dies); Hamasaiid, Dour, Dargusch, Loulou, Davidson and Wang, "Heat transfer
    at the casting/die interface in high pressure die casting", Metallurgical and Materials
    Transactions A 38 (2007) 1303-1316.
17. The pouring-time rules of gating practice, t = K √(mass) (for example Beeley, Foundry
    Technology, 2nd ed., Butterworth-Heinemann, 2001): the form; the K here is an order of
    magnitude.
18. Wlodawer, Directional Solidification of Steel Castings (Pergamon, 1966): the feeder's modulus
    at least 1.2 times the casting's.
