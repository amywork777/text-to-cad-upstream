# Materials

Isotropic, linear, room temperature. Name one in the study's `material`, or
give the numbers yourself. A static study reads E, ν and yield, and density for a `gravity` or
`acceleration` load. These are textbook values for a first pass; a
study that matters uses the supplier's datasheet through the object form
(`{"name": "...", "E_MPa": ..., "nu": ..., "yield_MPa": ...}`). An object named by a table name or
alias extends that entry and is called by its name ("Steel (structural, generic)"); one of its own is
called by its name tidied: its first letter capitalised ("soft silicone" is "Soft silicone") and a
slug's words spaced, an alloy code in capitals ("copper-c110" is "Copper C110").

| name (and aliases) | E (MPa) | ν | yield (MPa) | density (t/mm³) | notes |
| --- | --- | --- | --- | --- | --- |
| `steel` (`mild-steel`) | 200 000 | 0.30 | 250 | 7.85e-9 | generic structural / low-carbon |
| `stainless-304` (`304`, `stainless`, `ss304`) | 193 000 | 0.29 | 215 | 8.00e-9 | annealed |
| `aluminum-6061-t6` (`6061`, `6061-t6`, `aluminum`, `aluminium`) | 68 900 | 0.33 | 276 | 2.70e-9 | the default aluminium |
| `aluminum-7075-t6` (`7075`, `7075-t6`) | 71 700 | 0.33 | 503 | 2.81e-9 | |
| `titanium-6al-4v` (`titanium`, `ti-6al-4v`) | 113 800 | 0.342 | 880 | 4.43e-9 | |
| `brass` | 97 000 | 0.31 | 310 | 8.50e-9 | C36000, half hard |
| `abs` | 2 200 | 0.35 | 40 | 1.04e-9 | injection moulded; printed parts are weaker and anisotropic |
| `pla` | 3 500 | 0.36 | 60 | 1.24e-9 | printed; treat yield as an upper bound |
| `petg` | 2 100 | 0.38 | 50 | 1.27e-9 | printed |
| `nylon-pa12` (`nylon`, `pa12`) | 1 700 | 0.40 | 48 | 1.01e-9 | SLS / MJF |

Names are case-insensitive; spaces and underscores read as hyphens.

For printed polymers the model's assumptions are loose: layer adhesion,
infill and orientation change stiffness and strength by a factor of two or
more. Say so, and use a larger safety factor than for a machined metal part.

A material must be the same in every direction: an `orthotropic` block in the material object is
refused, with a sentence asking for its E_MPa and nu. For a directional material (printed layers,
wood, a fibre block), give the modulus along the direction that carries the load, say that you did,
and treat the answer as rough.

The tables below record further properties of the same materials (strength, fatigue, heat,
fracture, electrical). A static study does not read them; a material object may still give them,
and they are checked and kept with the study. The analyses that will read some of them are in
[planned-next.md](planned-next.md).

## Strength, fatigue and heat

Ultimate strength, fatigue strength, conductivity, expansion and specific heat. Override any of
them in the material object: `uts_MPa`, `endurance_MPa` with `endurance_cycles` (also accepted as
`fatigue_strength_MPa` and `fatigue_cycles`), `conductivity_W_mK`, `expansion_per_K` (per kelvin,
so `23.6e-6`), `specific_heat_J_kgK`.

| name | UTS (MPa) | endurance (MPa) | at cycles | k (W/(m·K)) | α (1e-6/K) | c (J/(kg·K)) | sources |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `steel` | 400 | 200 | 1e6 | 50 | 11 | 470 | [MatWeb A36], [MakeItFrom A36], [Shigley] |
| `stainless-304` | 505 | 240 | 1e7 | 16.2 | 17.3 | 500 | [ASM 304], [NiDI 304 fatigue] |
| `aluminum-6061-t6` | 310 | 96.5 | 5e8 | 167 | 23.6 | 896 | [ASM 6061-T6] |
| `aluminum-7075-t6` | 572 | 159 | 5e8 | 130 | 23.6 | 960 | [ASM 7075-T6] |
| `titanium-6al-4v` | 950 | 510 | 1e7 | 6.7 | 8.6 | 526 | [ASM Ti-6Al-4V] |
| `brass` | 393 | 138 | 1e8 | 116 | 20.5 | 377 | [CDA C36000] |
| `abs` | 43 | none | none | 0.17 | 90 | 1200 | [Novodur 433], [Röchling ABS] |
| `pla` | 60 (unverified) | none | none | 0.13 | 85 | 1800 | [Prusament PLA], [MakeItFrom PLA], [Omnexus CLTE] |
| `petg` | 50 | none | none | 0.20 | 68 | 1100 | [Prusament PETG], [HIPEX G PETG] |
| `nylon-pa12` | 48 | none | none | 0.144 | 109 | 2350 | [EOS PA 2200], [EOS PA 2200 2010] |

Notes, value by value:

- `steel` is generic structural steel, read as ASTM A36. UTS 400 MPa is A36's minimum (MatWeb: 400
  to 550). The endurance limit is Shigley's rule Se' = 0.5·Sut (200 MPa, which MakeItFrom also
  gives), taken at the rule's usual 1e6 cycles; the page fetched did not state the cycle count. k, α
  and c are MakeItFrom's A36 values (MatWeb's A36 bar sheet has no thermal data).
- `stainless-304`, annealed: UTS, k (0 to 100 °C), α (0 to 100 °C) and c from ASM. ASM gives no
  fatigue value; 240 MPa at 1e7 reversed-bending cycles is from a secondary page citing INCO/NiDI
  publication 2978 (MakeItFrom gives 210 MPa), so treat it as approximate.
- `aluminum-6061-t6` and `aluminum-7075-t6`: every value from ASM; the
  endurance is the R. R. Moore fully reversed strength at 5e8 cycles
  (aluminium has no true endurance limit). α over 20 to 100 °C.
- `titanium-6al-4v`, annealed grade 5: every value from ASM; 510 MPa at 1e7 is
  unnotched (ASM gives 240 MPa notched, Kt 3.3).
- `brass`, C36000 half hard: Copper Development Association, rod under 12 mm, the row that carries
  the fatigue strength (393 MPa UTS, 138 MPa at 1e8). Thicker rod is 380 to 400 MPa.
- `abs`: UTS 43 MPa is Novodur 433's tensile yield stress (ISO 527), the
  strength ABS datasheets quote; k, α and c are Röchling SustaABS's (NETZSCH
  gives c 1260 to 1680 J/(kg·K), α 80 to 100e-6/K).
- `pla`: Prusament's PLA datasheet gives tensile yield only (57 MPa filament, 51 MPa printed flat,
  59 MPa upright) and no thermal properties. UTS 60 MPa is the table's starting value and is
  unverified. k and c from MakeItFrom; α from Omnexus's CLTE table (85e-6/K).
- `petg`: UTS 50 MPa is Prusament PETG's tensile yield printed upright (47 flat).
  Prusament gives no thermal properties; k, α and c are from the HIPEX G PETG
  sheet (Eastman Eastar 6763 gives k 0.21, α 51e-6/K, c 1300 at 60 °C).
- `nylon-pa12`, EOS PA 2200 (SLS): UTS 48 MPa in X/Y (42 in Z) from EOS's current datasheet; k
  (0.144 across the layers, 0.127 along them), α and c from EOS's 2010 product information.

### Why some values are none

- Endurance, for `abs`, `pla`, `petg` and `nylon-pa12`: polymers have no endurance limit, and their fatigue strength depends on frequency, temperature, moisture and (printed) layer orientation; give the grade's S-N point from its datasheet

### Sources

- [MatWeb A36]: https://web.archive.org/web/20240902143212id_/https://matweb.com/search/DataSheet.aspx?MatGUID=d1844977c5c8440cb9a3a967f8909c3a
- [MakeItFrom A36]: https://makeitfrom.com/material-properties/ASTM-A36-SS400-S275-Structural-Carbon-Steel
- [Shigley]: Shigley's Mechanical Engineering Design, chapter 6 (Se' = 0.5·Sut for Sut up to 1400 MPa); solutions manual https://www.secs.oakland.edu/~latcha/ME4300/SM_PDF/CH6.pdf
- [ASM 304]: https://web.archive.org/web/20250327094625id_/https://asm.matweb.com/search/SpecificMaterial.asp?bassnum=mq304a
- [NiDI 304 fatigue]: https://tubingchina.com/Fatigue-Properties-and-Endurance-Limits-of-Stainless-Steel.htm (citing INCO/NiDI publication 2978)
- [ASM 6061-T6]: ASM Aerospace Specification Metals, asm.matweb.com bassnum=ma6061t6, read in the printout https://quickparts.com/wp-content/uploads/2024/05/Aluminum-6061.pdf
- [ASM 7075-T6]: https://web.archive.org/web/20241216135852id_/https://asm.matweb.com/search/SpecificMaterial.asp?bassnum=MA7075T6
- [ASM Ti-6Al-4V]: https://web.archive.org/web/20241204175911id_/https://asm.matweb.com/search/SpecificMaterial.asp?bassnum=MTP641
- [CDA C36000]: https://alloys.copper.org/alloy/C36000
- [Novodur 433]: INEOS Styrolution Novodur 433 ABS datasheet, https://www.protolabs.com/media/0q3bj4w5/id-pending-novodur-433-abs.pdf
- [Röchling ABS]: https://www.roechling.com/pl/industrial/materialy/thermoplastics/engineering-plastics/abs/sustaabs-grey-591062
- [Prusament PLA]: Prusament PLA technical data sheet v1.1 (2022-07-27), linked from https://prusament.com/materials/pla/
- [MakeItFrom PLA]: https://makeitfrom.com/material-properties/Polylactic-Acid-PLA-Polylactide
- [Omnexus CLTE]: https://web.archive.org/web/20240406205455id_/https://omnexus.specialchem.com/polymer-property/coefficient-of-linear-thermal-expansion
- [Prusament PETG]: https://storage.googleapis.com/prusa3d-content-prod-14e8-wordpress-prusament-prod/2023/10/9f8d2165-tds_prusament-petg_n_en.pdf
- [HIPEX G PETG]: https://pim.igepa.nl/Plaatmateriaal/Kunststof/PET-G/Technische%20datasheet%20HIPEX%20G%20PETG.pdf
- [EOS PA 2200]: https://www.eos.info/polymer-solutions/polymer-materials/data-sheets/mds-pa-2200
- [EOS PA 2200 2010]: https://www.sculpteo.com/media/imagecontent/PA2200_Product_information_03-10_en.pdf

## Fracture

The plane-strain fracture toughness K_IC and Paris's crack-growth law da/dN = C (ΔK)^m. Override
them in the material object: `fracture_toughness_MPa_sqrt_m`, `paris_C` (m per cycle, with ΔK in
MPa√m) and `paris_m`. Room temperature, in air. A value no source gives for the grade is none.

| name | K_IC (MPa√m) | Paris C (m/cycle) | Paris m | sources |
| --- | --- | --- | --- | --- |
| `steel` | none | 6.9e-12 | 3.0 | [Norton Paris] (ferritic-pearlitic steels) |
| `stainless-304` | none | 5.6e-12 | 3.25 | [Norton Paris] (austenitic stainless steels) |
| `aluminum-6061-t6` | 29 | none | none | [ASM 6061-T6 e] (T-L) |
| `aluminum-7075-t6` | 20 | none | none | [ASM 7075-T6] (S-L, the lowest of three) |
| `titanium-6al-4v` | 75 | none | none | [ASM Ti-6Al-4V] |
| `brass` | none | none | none | |
| `abs` | none | none | none | |
| `pla` | none | none | none | |
| `petg` | none | none | none | |
| `nylon-pa12` | none | none | none | |

Notes, value by value:

- `aluminum-7075-t6`: ASM gives K_IC 20 MPa√m in the S-L direction, 25 in T-L
  and 29 in L-T. The table takes the lowest, 20; a crack whose orientation in
  the plate or bar is known may use its own direction's value.
- `aluminum-6061-t6`: ASM gives 29 MPa√m, T-L orientation.
- `titanium-6al-4v`, annealed grade 5: ASM gives 75 MPa√m (no orientation stated).
- `steel` and `stainless-304`: Barsom's Paris fits for ferritic-pearlitic and austenitic stainless
  steels, from Norton's Machine Design table 6-2. The SI column there is labelled mm/cycle, but its
  U.S. column (3.60e-10 in/cycle, ksi√in, for ferritic-pearlitic) converts to 6.9e-12 m/cycle with
  ΔK in MPa√m, so C is per metre, as Barsom gives it. They are fits over many steels: a study that
  matters uses the grade's own da/dN data.
- K_IC is a plane-strain value: thinner sections are tougher (plane stress),
  so it is conservative for thin parts.

### Why some values are none (fracture)

- K_IC, for `steel`, `stainless-304` and `brass`: a tough, ductile metal like this tears plastically before a valid plane-strain K_IC can be measured, and no source cited here gives one for the grade; give fracture_toughness_MPa_sqrt_m from the supplier's test (or a J_IC converted to K), and treat LEFM as an approximation for it
- Paris C and m, for the aluminium alloys, titanium and `brass`: no source cited here gives Paris constants for this grade; give paris_C (m/cycle, ΔK in MPa√m) and paris_m from the alloy's crack-growth (da/dN) data at the load ratio it sees
- Every fracture value, for `abs`, `pla`, `petg` and `nylon-pa12`: a polymer's (and a printed part's) toughness and crack growth depend on grade, temperature, rate, moisture and layer orientation; give fracture_toughness_MPa_sqrt_m and paris_C, paris_m from the grade's own test data

### Sources (fracture)

- [Norton Paris]: Robert L. Norton, Machine Design: An Integrated Approach, 6th edition, table 6-2 (data from Barsom), https://designofmachinery.com/wp-content/uploads/2021/02/Chap-06-MD-6ed-p.360-361.pdf
- [ASM 6061-T6 e], [ASM 7075-T6] and [ASM Ti-6Al-4V]: as listed under the electrical and the strength sources (asm.matweb.com).

## Electrical and magnetic

Resistivity, relative permittivity (dielectrics only) and relative permeability. Override them in
the material object: `resistivity_ohm_m`, `relative_permittivity`, `relative_permeability`. Room
temperature, DC (permittivity at the frequency given).

| name | resistivity (ohm·m) | eps_r | mu_r | sources |
| --- | --- | --- | --- | --- |
| `steel` | 1.4368e-7 | none | none | [MakeItFrom A36] (12 % IACS), [EngToolbox permeability] |
| `stainless-304` | 7.2e-7 | none | 1.008 | [ASM 304] |
| `aluminum-6061-t6` | 3.99e-8 | none | 1.000022 | [ASM 6061-T6 e], [EngToolbox permeability] |
| `aluminum-7075-t6` | 5.15e-8 | none | 1.000022 | [ASM 7075-T6], [EngToolbox permeability] |
| `titanium-6al-4v` | 1.78e-6 | none | 1.00005 | [ASM Ti-6Al-4V] |
| `brass` | 6.6312e-8 | none | 1.0 (unverified) | [CDA C36000 e] (26 % IACS) |
| `abs` | 1e13 | 3.1 | 1.0 (unverified) | [Röchling ABS], [Novodur P2H-AT] |
| `pla` | 1e14 (unverified) | 3.0 (unverified) | 1.0 (unverified) | [PLA printed permittivity] |
| `petg` | 1e13 | 2.6 | 1.0 (unverified) | [Eastar 6763] |
| `nylon-pa12` | 1e12 | 3.8 | 1.0 (unverified) | [EOS PA 2200 e], [Professional Plastics] |

Notes, value by value:

- Resistivity from % IACS is 1.7241e-8 ohm·m / (% IACS / 100): A36 12 % gives 1.4368e-7, C36000 26 %
  gives 6.6312e-8. ASM's metals are given in ohm·cm (x 0.01).
- `aluminum-*`: the permeability is Engineering Toolbox's for aluminium, not
  for the alloy. `titanium-6al-4v`: ASM's 1.00005 at 1.6 kA/m.
- `brass`: no brass permeability was found; copper's is 0.999994
  ([EngToolbox permeability]), so 1.0 is used, unverified.
- `abs`: Röchling SustaABS gives 10^15 ohm·cm and eps_r 3.1 (IEC 60250, frequency
  not stated); INEOS Novodur P2H-AT gives eps_r 2.9 at 1 MHz and > 1e13 ohm·m.
- `pla`: no datasheet with PLA's resistivity or permittivity could be fetched; 1e14 ohm·m and 3.0
  are typical polyester values, unverified. A study of 3D printed PLA measured eps_r 1.78 to 2.81,
  falling with infill ([PLA printed permittivity]).
- `petg`: Eastman Eastar 6763, 10^15 ohm·cm (ASTM D257) and eps_r 2.6 at 1 kHz (2.4 at 1 MHz).
- `nylon-pa12`: EOS PA 2200 gives 10^13 to 10^15 ohm·cm and eps_r 3.8 at 1 kHz, both strongly
  dependent on temperature and humidity; 1e12 ohm·m is the middle of that range.
- Polymers' permeability: 1.0 for all four, the usual assumption for a non-magnetic plastic; no
  source states it for these grades (Engineering Toolbox gives 1 for PTFE), so it is unverified.

### Why some values are none (electrical)

- Permittivity, for every metal: a metal conducts, so it has no permittivity: in an electric study it is an equipotential (one voltage throughout), held or floating
- Permeability, for `steel`: structural steel is ferromagnetic: its permeability depends on the field and saturates (Engineering Toolbox lists about 100 for carbon steel); give relative_permeability from the grade's B-H curve at the field expected

### Sources (electrical)

- [EngToolbox permeability]: https://www.engineeringtoolbox.com/permeability-d_1923.html
- [ASM 6061-T6 e]: https://web.archive.org/web/20241217181844id_/https://asm.matweb.com/search/SpecificMaterial.asp?bassnum=MA6061T6
- [CDA C36000 e]: https://web.archive.org/web/20260504212850id_/https://alloys.copper.org/alloy/C36000
- [Novodur P2H-AT]: https://plasticker.de/docs/recybase/35956_1785994693.pdf
- [PLA printed permittivity]: https://pmc.ncbi.nlm.nih.gov/articles/PMC9942642/
- [Eastar 6763]: https://eastman.com/content/dam/eastman/corporate/en/literature/m/mbs80.pdf (table 3)
- [EOS PA 2200 e]: https://www.amf.uzh.ch/dam/jcr:59a8b14a-c212-4693-8443-d5e543aeabe2/Material-Data-PA2200-ENGLISH.pdf
- [Professional Plastics]: https://www.professionalplastics.com/professionalplastics/ElectricalPropertiesofPlastics.pdf
- [MakeItFrom A36], [ASM 304], [ASM 7075-T6], [ASM Ti-6Al-4V] and [Röchling ABS]: as listed under Sources above.
