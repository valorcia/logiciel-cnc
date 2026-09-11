# Architecture du dépôt et interfaces Python

Complément de l'ADR-001. Ce document décrit **où vit quoi** et **qui a le droit
d'appeler qui**.

## 1. Arborescence

```
logiciel-cnc/
├── pyproject.toml
├── docs/
│   ├── adr/ADR-001-architecture-fondatrice.md
│   ├── audit/dependencies-licenses.md
│   ├── algorithms/accessibility-solver.md
│   ├── algorithms/orientation-solver.md
│   ├── testplan/plan-de-tests.md
│   └── architecture.md
├── src/xyzac/
│   ├── geometry_core/        types.py, brep.py, sphere.py
│   ├── machine_model/        machine.py, setup.py
│   ├── tool_model/           assembly.py
│   ├── stock_engine/         stock.py
│   ├── feature_engine/       revolution.py
│   ├── accessibility_solver/ solver.py            ← différenciateur (1/2)
│   ├── orientation_solver/   solver.py            ← différenciateur (2/2)
│   ├── collision_engine/     field.py, tool_collision.py
│   ├── kinematics_solver/    solver.py
│   ├── simulation_engine/    scene.py
│   ├── turning_engine/       interfaces.py
│   ├── safety_state_machine/ machine.py
│   ├── subtractive_slicer/   interfaces.py        ← stub M1
│   ├── strategy_planner/     interfaces.py        ← stub M1
│   ├── vision_service/       interfaces.py        ← stub M1
│   ├── probing_service/      interfaces.py        ← stub M1
│   ├── postprocessor_linuxcnc/ interfaces.py      ← stub M1, verrouillé
│   ├── linuxcnc_gateway/     interfaces.py        ← stub M1, verrouillé
│   ├── recipe_profiles/      interfaces.py        ← stub M1
│   ├── assembly_calibration/ interfaces.py        ← stub M1
│   └── ui/                   render.py
├── tests/         conftest, 5 fichiers, corpus/ (20 STEP + manifeste)
├── tools/         make_corpus.py, demo_vertical_slice.py
└── out/           rendus PNG (non versionnés)
```

## 2. Règles de dépendance

Elles ne sont pas indicatives : la dernière est **vérifiée par un test**
(`test_no_module_besides_gateway_imports_a_machine_transport`).

1. `geometry_core/brep.py` est **le seul** fichier à importer `OCP`. Un
   changement de bindings se traite là et nulle part ailleurs (ADR-001 / D1).
2. Le flux va toujours dans le même sens : `geometry_core` → modèles →
   solveurs → simulation → sécurité → post-processeur → passerelle.
   Aucun module amont n'importe un module aval.
3. `simulation_engine` n'importe jamais `linuxcnc_gateway`. Le digital twin
   ne peut pas, même par erreur, atteindre une machine.
4. **Seul** `linuxcnc_gateway` peut ouvrir un transport machine
   (`socket`, `telnetlib`, `serial`, `linuxcnc`).
5. `vision_service` ne retourne que des observations. Aucune de ses fonctions
   ne produit de consigne d'axe.

## 3. Interfaces principales

### geometry_core

```python
load_step(path) -> TopoDS_Shape
save_step(shape, path) -> Path
bounding_box(shape) -> AABB
volume(shape) -> float
face_info(shape) -> list[FaceInfo]          # type, aire, axe de révolution
tessellate(shape, deflection) -> (verts, tris, face_ids)
sample_surface(shape, spacing) -> SampledSurface   # espacement BORNÉ
sample_face(shape, face_index, spacing) -> SampledSurface
icosphere(subdivisions) -> SphereGrid       # + connected_components()
```

`SampledSurface.max_spacing` est la garantie dont dépend tout le moteur de
collision : aucun point de la surface n'est plus loin que cette valeur d'un
point échantillonné.

### tool_model

```python
ToolAssembly(segments=[ToolSegment(role, z_start, z_end, r_start, r_end)], ...)
  .radius_profile(z) -> np.ndarray     # rayon de l'enveloppe, vectorisé
  .cutting_length, .max_radius, .total_length, .gauge_length
build_endmill(id, diameter, flute_length, stickout, holder_type, corner_radius, ...)
build_ballnose(id, diameter, flute_length, ...)
```

Validations refusant un modèle dangereux : pile non contiguë, pile ne
démarrant pas au bec, jauge dépassant la pile modélisée.

### machine_model

```python
MachineKinematics(x, y, z, a, c, c_mode, pivot_a, pivot_c, ...)
  .tool_axis_in_part(a_deg, c_deg) -> np.ndarray
  .rotation_machine_from_part(a_deg, c_deg) -> (3,3)
Setup(machine, part_step_path, stock, fixtures, tools, work_offset)
  .setup_hash() -> str     # toute approbation y est liée
```

### collision_engine

```python
ObstacleField.build(part_points, part_spacing, finish_allowance,
                    stock_points, fixture_points, safety_clearance) -> ObstacleField
ToolCollisionChecker(tool)
  .check(tcp, axis, obstacles, cutting_depth, cutting_allowance) -> CollisionReport
  .check_many(tcps, axes, obstacles, ...) -> (feasible, margin, blocking)
```

`check_many` accepte **un TCP par orientation** — obligatoire dès qu'il y a un
rayon de bec.

### accessibility_solver / orientation_solver

```python
AccessibilitySolver(tool, machine, obstacles, config)
  .solve_point(contact, normal) -> AccessibilityMap
  .solve_points(contacts, normals) -> list[AccessibilityMap]

AccessibilityMap
  .feasible, .margin, .reason (RejectReason), .a_deg, .c_deg
  .cones() -> list[np.ndarray]        # composantes connexes
  .dominant_reason() -> RejectReason  # + REMEDY[reason]

OrientationSolver(machine, tool, weights, candidates_per_point, preferred_lead_deg)
  .solve(amaps, path_points, feed_dirs) -> OrientationPlan
  .segment_3plus2(amaps, plan) -> list[OrientationSegment]
  .refine(plan, amaps, collision_check) -> OrientationPlan

OrientationPlan
  .a_deg, .c_deg (déroulé), .margin, .segments, .indexed_fraction, .feasible
```

### safety_state_machine

```python
SafetyStateMachine(setup_hash)
  .define_setup(h) → .pass_collision(ok) → .pass_kinematics(ok)
                   → .pass_simulation(ok) → .approve(operator)
  .may_postprocess(current_hash) -> bool
  .require_postprocess(current_hash)      # lève SafetyViolation
  .audit_trail() -> str
```

Les portes ne peuvent pas être sautées : le graphe de transitions les refuse.

## 4. Ce qui est implémenté au jalon M1

| Module | État |
|---|---|
| geometry_core, machine_model, tool_model, stock_engine | **implémenté** |
| collision_engine, kinematics_solver | **implémenté** |
| accessibility_solver, orientation_solver | **implémenté (prototype R&D)** |
| feature_engine (révolution), simulation_engine (scène), ui (rendu) | **implémenté** |
| safety_state_machine | **implémenté** |
| turning_engine | détection implémentée, génération **non** |
| subtractive_slicer, strategy_planner, vision, probing, recipes, calibration | **interfaces seules** |
| postprocessor_linuxcnc, linuxcnc_gateway | **verrouillés** (ADR-001 §6) |
