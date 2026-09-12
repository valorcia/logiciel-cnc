# Architecture du dépôt et interfaces Python

Complément de l'ADR-001. Ce document décrit **où vit quoi** et **qui a le droit
d'appeler qui**.

## 1. Arborescence

```
logiciel-cnc/
├── pyproject.toml
├── docs/
│   ├── adr/ADR-001-architecture-fondatrice.md … ADR-006-jalon-M6.md
│   ├── audit/dependencies-licenses.md
│   ├── algorithms/accessibility-solver.md
│   ├── algorithms/orientation-solver.md
│   ├── testplan/plan-de-tests.md
│   └── architecture.md
├── src/xyzac/
│   ├── geometry_core/        types.py, brep.py, sphere.py, voxelize.py,
│   │                         healing.py, curvature.py
│   ├── machine_model/        machine.py, setup.py
│   ├── tool_model/           assembly.py
│   ├── stock_engine/         stock.py, material.py
│   ├── feature_engine/       revolution.py
│   ├── accessibility_solver/ solver.py            ← différenciateur (1/2)
│   ├── orientation_solver/   solver.py            ← différenciateur (2/2)
│   ├── collision_engine/     field.py, tool_collision.py, spatial.py,
│   │                         machine_guard.py, sweep.py, exact_gouge.py
│   ├── kinematics_solver/    solver.py
│   ├── simulation_engine/    scene.py, validator.py
│   ├── turning_engine/       interfaces.py, profile.py
│   ├── safety_state_machine/ machine.py
│   ├── subtractive_slicer/   interfaces.py, slicer.py, finishing.py
│   ├── strategy_planner/     interfaces.py, planner.py
│   ├── vision_service/       interfaces.py        ← stub M1
│   ├── probing_service/      interfaces.py        ← stub M1
│   ├── postprocessor_linuxcnc/ interfaces.py      ← stub M1, verrouillé
│   ├── linuxcnc_gateway/     interfaces.py        ← stub M1, verrouillé
│   ├── recipe_profiles/      interfaces.py        ← stub M1
│   ├── assembly_calibration/ interfaces.py        ← stub M1
│   └── ui/                   render.py
├── tests/         conftest, 11 fichiers, corpus/ (20 STEP sains + 3 dégradés)
├── tools/         make_corpus.py, make_degraded_corpus.py,
│               demo_vertical_slice.py, demo_m2_pipeline.py, demo_m3_pipeline.py
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
  .subset_near(center, radius)            # index spatial adaptatif
  .subset_capsule(p0, p1, radius)         # requête du balayage
ToolCollisionChecker(tool)
  .check(tcp, axis, obstacles, cutting_depth, cutting_allowance) -> CollisionReport
  .check_many(tcps, axes, obstacles, ...) -> (feasible, margin, blocking)

MachineGuard(machine, tool)
  .check_pose(tcp_machine, a_deg, c_deg) -> MachineCheck
  .check_many(tcps_machine, ac) -> np.ndarray[bool]

SweepChecker(machine, tool, max_step_mm)
  .displacement_bound(tcp0, axis0, tcp1, axis1) -> float   # majorant STRICT
  .check_segment(...) -> SweepReport
  .check_path(tcps, axes, a_seq, c_seq, obstacles) -> list[SweepReport]

verify_gouge_exact(part_shape, tool, tcp, axis, ...) -> GougeResult   # B-Rep exact
```

`check_many` accepte **un TCP par orientation** — obligatoire dès qu'il y a un
rayon de bec.

### stock_engine / simulation_engine (M2)

```python
MaterialState.from_setup(stock, part_verts, part_tris, pitch) -> MaterialState
  .remove_tool_sweep(tcps, axes, tool) -> int      # voxels enlevés
  .count_gouged_voxels(tcps, axes, tool) -> int    # matière protégée touchée
  .carve_to_finished() -> int
  .boundary_points() -> (points, inflation)

TrajectoryValidator(setup, obstacles, tool, ...)
  .validate(plan, contacts, normals) -> ValidationReport   # V1..V4
make_pose_verifier(setup, obstacles, tool, contacts, normals, ...) -> verify
run_simulation_gate(validator, plan, contacts, normals, safety) -> ValidationReport
```

`make_pose_verifier` est le **point unique** de construction de la fonction
`verify(index, direction)`, partagée par la segmentation 3+2 et le raffinement.
Elle vérifie la pièce **et** la machine — une version qui n'en vérifiait qu'une
a produit un plan hors course.

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
| geometry_core (+ voxelisation), machine_model, tool_model | **implémenté** |
| stock_engine (+ suivi de matière voxel) | **implémenté** |
| collision_engine (poses, balayage, machine, gouge exacte, index) | **implémenté** |
| kinematics_solver | **implémenté** |
| accessibility_solver, orientation_solver | **implémenté (prototype R&D)** |
| simulation_engine (scène + validateur 4 points) | **implémenté** |
| feature_engine (révolution), ui (rendu) | **implémenté** |
| safety_state_machine | **implémenté** |
| turning_engine | détection implémentée, génération **non** |
| subtractive_slicer (ébauche indexée), strategy_planner (couverture gloutonne) | **implémenté** |
| geometry_core/healing (diagnostic + réparation gardée) | **implémenté** |
| vision, probing, recipes, calibration | **interfaces seules** |
| postprocessor_linuxcnc, linuxcnc_gateway | **verrouillés** (ADR-001 §6, motif mis à jour en M2) |


## 5. Ajouts du jalon M3

### subtractive_slicer

```python
slice_for_direction(material, direction, tool, layer_thickness, stepover_ratio,
                    safety_clearance) -> SliceResult
continuous_path(result, point_spacing, layers=None) -> (points, is_rapid)
toolpath_points(result, point_spacing) -> (cut_points, normals)
simulate_removal(material, result, tool) -> RemovalStats
indexed_frame(direction) -> (3,3)     # R @ direction = +Z
```

`continuous_path` inclut les **liaisons** (remontée au plan de dégagement,
déplacement, replongée) ; `toolpath_points` ne rend que les points de coupe,
puisqu'une liaison n'enlève rien.

### strategy_planner

```python
candidate_directions(shape, setup) -> list[np.ndarray]
evaluate_candidates(directions, material, setup) -> list[DirectionCandidate]
plan_roughing(shape, setup, material, tool, ...) -> (ProcessPlan, PlanReport)
indexed_orientation_plan(points, direction, setup) -> OrientationPlan
```

### stock_engine (matière)

```python
MaterialState.reachable_from(direction) -> mask
MaterialState.protect_fixtures(setup) -> int      # les bridages sont protégés
MaterialState.protected_boundary_points() -> (points, inflation)
```

### geometry_core/healing

```python
load_step_checked(path) -> (shape, StepDiagnosis, HealingResult)
require_usable(shape, diagnosis)                  # lève UnusableShapeError
```

`StepDiagnosis` sépare `geometry_issues` (réparables) de
`plausibility_warnings` (à trancher par l'utilisateur). `HealingResult.resolved`
dit si la réparation a **réellement** agi.

### simulation_engine

```python
validate_roughing_progressive(setup, material, slice_result, tool, ...) -> OperationReport
```

Valide couche par couche en enlevant la matière au fur et à mesure : c'est
l'ordre dans lequel la machine travaille, et le seul état contre lequel la
question a un sens.


## 6. Ajouts du jalon M4

### subtractive_slicer/finishing

```python
scallop_stepover(tool_radius, scallop_mm) -> float
group_faces_by_normal(shape, tol_deg, curved_above_deg) -> list[list[int]]
generate_finishing_passes(shape, face_indices, tool, scallop_mm,
                          waterline_above_deg) -> FinishingPass | None
```

`FinishingPass.topology` vaut `"parallele"` (bandes dans le plan tangent) ou
`"waterline"` (niveaux constants autour de l'axe du groupe). Le choix se fait
sur l'étalement des normales : au-delà de 60°, le plan tangent moyen n'existe
plus et les bandes se replieraient.

Une fraise à **bout droit** est refusée : elle laisse une marche à chaque passe.

### strategy_planner

```python
plan_finishing(shape, setup, obstacles, tool, scallop_mm,
               max_points_per_pass, stride) -> (ProcessPlan, list[FinishingOpReport])
```

`FinishingOpReport` distingue l'étalement du **segment évalué** de celui de la
**passe complète**, et affiche la couverture : un mode `3+2` obtenu sur le pôle
d'une calotte ne dit rien du reste de la calotte, et le rapport le dit.

### accessibility_solver

```python
AccessibilitySolver.solve_points_adaptive(contacts, normals, stride,
                                          max_candidates) -> list[AccessibilityMap]
```

Résout complètement un point sur `stride`, puis n'évalue aux points
intermédiaires qu'un ensemble candidat réduit — **augmenté des directions
admissibles en toutes les ancres**, sans quoi la faisabilité de la séquence
dépendrait de la chance du classement (voir ADR-004 / D36).

## 7. Ajouts du jalon M5

### geometry_core/curvature

```python
face_curvature(shape, face_index, n_u, n_v) -> FaceCurvature | None
curvature_stepover(tool_radius, scallop_mm, kappa) -> float
```

`FaceCurvature.kappa_worst` est la courbure principale **la plus convexe** de la
face — celle qui majore la crête, donc celle qui dimensionne le pas. Convention
de signe : positive sur une bosse vue du côté de la normale sortante. Le signe
tient compte de l'orientation topologique de la face (`TopAbs_REVERSED`), faute
de quoi convexe et concave s'échangent.

`curvature_stepover` est une **forme fermée exacte** (loi des cosinus sur le
cercle osculateur), pas un développement, et vaut exactement
`subtractive_slicer.scallop_stepover` à `kappa = 0`. Un creux plus serré que
l'outil lève `ValueError` : l'outil n'en atteint pas le fond, et aucun pas n'y
remédie.

### turning_engine/profile

```python
revolution_profile(shape, axis_point, axis_dir, n_z, n_theta,
                   sample_spacing) -> RevolutionProfile
plan_turning_passes(profile, tool, stock_radius, depth_of_cut,
                    finish_allowance) -> TurningPlanReport
```

Le tournage est le seul module à travailler sur une géométrie **exacte** plutôt
que sur le test discret conservatif du reste du moteur : une pièce de révolution
est entièrement décrite par sa silhouette `(z, r)`, et une passe est une courbe
dans ce plan.

`RevolutionProfile.out_of_round()` mesure le défaut de circularité **sur θ**
(rayon maximal par secteur angulaire, étendue P95 − P5 sur les secteurs), et non
sur l'étendue d'une tranche : sinon la variation axiale d'un épaulement se
confond avec un méplat.

`TurningPlanReport.feasible` est faux, avec les zones nommées, si le profil est
plus raide que le dégagement de l'outil ou si le brut passe sous le profil. La
vérification a lieu **avant** toute génération de passes.

`turning_engine.require_c_mode` reste le verrou : passer en broche continue
invalide l'approbation de sécurité (ADR-001 / D8).

### subtractive_slicer/finishing

`generate_finishing_passes(..., use_curvature=True)` prend désormais le pas dans
la courbure mesurée du groupe de faces. Sur le dôme C10 le pas se resserre de
6,2 %, dans la cavité C11 il s'élargit de 8,5 %.

## 8. Ajouts du jalon M6

### collision_engine/machine_guard

```python
MachineGuard.check_many(tcps_machine, ac, *, return_travel=False)
    -> mask | (mask, travel_mask)
```

`return_travel=True` rend le masque des poses **dans les courses linéaires**,
la seule information qui distingue « hors course » de « collision organe ». Le
solveur d'accessibilité la re-dérivait par un test scalaire par rejet — 105
appels par point de contact, 57 % du temps total, pour retrouver ce que la
fonction appelée avait déjà en main.

### accessibility_solver — ordre des étages

`AccessibilityConfig.guard_first` (défaut `True`) place la garde machine
**avant** le test pièce. La faisabilité étant le ET de deux masques
indépendants, elle ne dépend pas de l'ordre — et un test différentiel l'exige,
orientation par orientation. Ce qui dépend de l'ordre :

- le **coût** : le test pièce porte sur 7 candidats au lieu de 114 sur une
  calotte ;
- la **cause rapportée** pour un candidat bloqué par les deux : la machine
  gagne, parce que c'est la contrainte liante ;
- la **complétude du champ de marges** : mettre `False` pour l'obtenir en
  entier, ce dont la visualisation des rejets a besoin.

### collision_engine/exact_gouge

```python
certify_plan_exact(part_shape, tool, tcps, axes, *, cutting_depth,
                   tolerance_mm, max_queries, check_cutting) -> GougeCertificate
```

Remplace le **sondage** de `verify_plan_sparse` par une **preuve**, en deux
volets parce qu'il y a deux physiques :

- `holder_proven` : aucun tronçon non coupant ne touche la pièce, sur tout le
  parcours. Obtenu par majoration du déplacement (`|Δtcp| + reach·angle`), donc
  avec un nombre de requêtes gouverné par la garde disponible et non par le
  nombre de poses — 3 requêtes pour 120 poses au-dessus d'un bloc.
- `cutting_tested` : l'arête de coupe, tangente à la surface par construction
  et donc incertifiable par la distance, est vérifiée **en chaque pose**.

`complete` exige les deux. Les intervalles non couverts sortent en
`uncertified` **avec leur position** ; un budget épuisé rend un certificat
incomplet, jamais optimiste.

### turning_engine/profile — corps de l'outil

```python
TurningToolBody.external(nose_offset_mm, width_front_mm, width_back_mm,
                         height_mm, feed) -> TurningToolBody
TurningToolBody.grooving(blade_width_mm, nose_offset_mm, depth_mm)
check_body_clearance(profile, body, z, r, *, clearance_mm, spacing)
    -> list[BodyInterference]
plan_turning_passes(..., body=None, body_clearance_mm=0.2)
```

La silhouette ne contient que le **corps**, à partir de la hauteur de
plaquette : le flanc de la plaquette contre la pente locale est déjà mesuré par
`too_steep_zones`, et l'y remettre faisait mesurer deux fois la même limite
physique — tout devenait infaisable.

`TurningPlanReport.body_checked` distingue « dégagé » de « non vérifié ». Sans
silhouette fournie, le rapport l'écrit au lieu de laisser une liste vide passer
pour un verdict.
