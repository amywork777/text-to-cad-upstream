# examples models

The repo's demo-model corpus as one `$cad-project`: every part and assembly is
a runnable model script directly under `src/`, and every artifact lands in a
format folder at the project root (`STEP/`, `STL/`, `3MF/`, `GLB/`). Nothing
here is committed except this `src/` tree and `imported/` — build what you need.

```bash
python models/examples/src/mounting_plate.py     # one model
ls models/examples/src/*.py | xargs -n1 -P4 python   # the whole corpus
```

Unchanged models are no-ops, so "build if missing" and "rebuild" are the same
command. Shared helper modules live in `src/lib/` (`part_common`,
`simple_model_library`, `mx_switch_socket`) — plain modules, never models.
Because the scripts sit directly in `src/`, `from lib import ...` and
`import <sibling_model>` both resolve with no path setup.

Two models carry kinematics and choreography: `planetary_gear_assembly`
(mates + a `drive` coupling + `quarter_cycle`/`half_cycle` poses) and
`mars_rover_concept` (27 mates, 7 couplings, 4 poses). Their `.anim.js` clips
sit beside the scripts and are copied into the artifact sidecar at build.

A handful of models declare mesh exports so the STL/3MF/GLB doors have real
fixtures to work against; `miniature_spiral_staircase` declares a `_highres`
variant at `mesh_tolerance=4e-4` to exercise the tolerance path.

`imported/import-smoke.step` is a committed SOURCE file (the viewer launch
test's fixture), not an output.

### Parts

| Script | Artifact | Description |
|--------|----------|-------------|
| `basic_shape_mating_test_fixture.py` | `STEP/basic_shape_mating_test_fixture.step + 3MF/basic_shape_mating_test_fixture.3mf` | Primitive-shape mating fixture (box/cone/sphere/cylinder on a base plate) |
| `cam_follower_roller.py` | `STEP/cam_follower_roller.step` | Cam follower roller with central bearing bore and rounded outer profile |
| `centrifugal_impeller.py` | `STEP/centrifugal_impeller.step` | Single solid centrifugal impeller |
| `circular_flange.py` | `STEP/circular_flange.step` | Circular flange model |
| `clevis_bracket_lightening_cutouts.py` | `STEP/clevis_bracket_lightening_cutouts.step` | Clevis bracket model |
| `cylindrical_cap.py` | `STEP/cylindrical_cap.step` | Cylindrical cap with hollow interior, top boss, and rounded external edges |
| `cylindrical_spacer_sleeve.py` | `STEP/cylindrical_spacer_sleeve.step` | Cylindrical spacer sleeve with a central through-bore and rounded rim edges |
| `electronics_enclosure_base.py` | `STEP/electronics_enclosure_base.step` | Single solid open-top electronics enclosure base |
| `flywheel_disk.py` | `STEP/flywheel_disk.step` | Flywheel disk with central bore, annular rim, and lightening holes |
| `gusset_plate.py` | `STEP/gusset_plate.step` | Gusset plate with a triangular web, base holes, and softened perimeter edges |
| `keyed_shaft_hub.py` | `STEP/keyed_shaft_hub.step` | Keyed shaft hub with central bore, keyway slot, and bolt-hole pattern |
| `l_bracket.py` | `STEP/l_bracket.step` | L-bracket model |
| `motorcycle_helmet_fidget.py` | `STEP/motorcycle_helmet_fidget.step` | Motorcycle helmet fidget with a Cherry MX switch socket |
| `motorcycle_seat_fidget.py` | `STEP/motorcycle_seat_fidget.step` | Motorcycle pillion (backseat) fidget with a Cherry MX switch socket |
| `motorcycle_shock_fidget.py` | `STEP/motorcycle_shock_fidget.step` | Motorcycle shock absorber fidget with a Cherry MX switch socket |
| `motorcycle_wheel_fidget.py` | `STEP/motorcycle_wheel_fidget.step` | Motorcycle wheel fidget with a Cherry MX switch socket |
| `mounting_plate.py` | `STEP/mounting_plate.step + STL/mounting_plate.stl, 3MF/mounting_plate.3mf, GLB/mounting_plate.glb` | Mounting plate with central circular cutout, elongated side slot, four corner holes, and rounded edges |
| `open_top_electronics_enclosure.py` | `STEP/open_top_electronics_enclosure.step` | Open-top electronics enclosure model |
| `print_in_place_hinge.py` | `STEP/print_in_place_hinge.step` | Print-in-place barrel hinge for FDM printing |
| `print_in_place_multi_pivot_phone_holder.py` | `STEP/print_in_place_multi_pivot_phone_holder.step` | Print-in-place multi-pivot holder with a phone/tablet cradle for FDM printing |
| `pulley_wheel.py` | `STEP/pulley_wheel.step` | Pulley wheel with a central hub, outer groove, and circular through-bore |
| `radial_engine_cylinder.py` | `STEP/radial_engine_cylinder.step` | Radial-engine-style cylinder model |
| `rectangular_calibration_block.py` | `STEP/rectangular_calibration_block.step` | Rectangular calibration block model |
| `rectangular_clamp_block.py` | `STEP/rectangular_clamp_block.step` | Rectangular clamp block with a split slot and two transverse screw holes |
| `research_humanoid.py` | `STEP/research_humanoid.step` | Production-realistic, adult-scale humanoid research platform |
| `retainer_plate.py` | `STEP/retainer_plate.step` | Retainer plate with elongated slot, two circular holes, and chamfered perimeter |
| `shaft_collar.py` | `STEP/shaft_collar.step` | Shaft collar with a central bore, radial set-screw hole, and chamfered faces |
| `small_enclosure_cover.py` | `STEP/small_enclosure_cover.step` | Small enclosure cover with raised rim, corner screw holes, and shallow recessed center |
| `spur_gear_blank.py` | `STEP/spur_gear_blank.step + STL/spur_gear_blank.stl, 3MF/spur_gear_blank.3mf, GLB/spur_gear_blank.glb` | Spur gear blank with central bore, raised hub, and simplified perimeter teeth |
| `square_mounting_block.py` | `STEP/square_mounting_block.step` | Square mounting block with a vertical through-hole and two side clearance holes |
| `stepped_shaft_keyway.py` | `STEP/stepped_shaft_keyway.step` | Stepped shaft with keyway model |
| `t_slot_slider_block.py` | `STEP/t_slot_slider_block.step` | T-slot slider block with central channel, side relief cuts, and mounting holes |

### Assemblies

| Script | Artifact | Description |
|--------|----------|-------------|
| `compact_humanoid.py` | `STEP/compact_humanoid.step` | Original 28-DOF compact humanoid research platform concept |
| `cutaway_turbofan_engine.py` | `STEP/cutaway_turbofan_engine.step` | Labeled multi-body cutaway turbofan display model |
| `flying_car.py` | `STEP/flying_car.step` | Four-rotor flying car concept |
| `lunar_rover_corner_assembly.py` | `STEP/lunar_rover_corner_assembly.step` | Lunar rover corner module: wheel, hub motor, suspension |
| `mars_rover_concept.py` | `STEP/mars_rover_concept.step` | Mars rover concept on terrain, mated + animated |
| `mechanical_iris_aperture.py` | `STEP/mechanical_iris_aperture.step` | Labeled mechanical iris aperture assembly |
| `miniature_spiral_staircase.py` | `STEP/miniature_spiral_staircase.step + STL/miniature_spiral_staircase_highres.stl, 3MF/miniature_spiral_staircase_highres.3mf, GLB/miniature_spiral_staircase_highres.glb` | Labeled miniature spiral staircase STEP compound |
| `motorcycle_shock_absorber.py` | `STEP/motorcycle_shock_absorber.step` | Motorcycle rear shock absorber (coilover damper) assembly |
| `pelican_riding_bicycle.py` | `STEP/pelican_riding_bicycle.step` | Pelican riding a bicycle (organic + mechanical mix) |
| `photo_coffee_cup.py` | `STEP/photo_coffee_cup.step` | Photo-inspired takeaway coffee cup model |
| `planetary_gear_assembly.py` | `STEP/planetary_gear_assembly.step + STL/planetary_gear_assembly.stl, 3MF/planetary_gear_assembly.3mf, GLB/planetary_gear_assembly.glb` | Labeled simplified planetary gear assembly |
| `planetary_gear_stage.py` | `STEP/planetary_gear_stage.step` | Simplified planetary gear assembly |
| `robotic_hand_end_effector.py` | `STEP/robotic_hand_end_effector.step` | Labeled cybernetic robotic hand end-effector STEP assembly |
| `sculpted_humanoid.py` | `STEP/sculpted_humanoid.step` | Sculpted full-scale humanoid research platform |
| `six_axis_industrial_robot_arm.py` | `STEP/six_axis_industrial_robot_arm.step` | Labeled six-axis industrial robot arm display assembly |
| `six_blade_open_propeller.py` | `STEP/six_blade_open_propeller.step` | Six-blade open propeller |
| `spiral_staircase.py` | `STEP/spiral_staircase.step` | Miniature spiral staircase model |

Build: `python src/<script>` per row; unchanged models are no-ops.
Imported sources: `imported/import-smoke.step` (committed, no script).
