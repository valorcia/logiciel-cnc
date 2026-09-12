# Architecture du dépôt et interfaces Python

Complément de l'ADR-001. Ce document décrit **où vit quoi** et **qui a le droit
d'appeler qui**.

## 1. Arborescence

```
logiciel-cnc/
├── pyproject.toml
├── docs/
│   ├── adr/ADR-001-architecture-fondatrice.md … ADR-010-jalon-M10.md
│   ├── banc-de-debug.md
│   ├── audit/dependencies-licenses.md
│   ├── algorithms/accessibility-solver.md
│   ├── algorithms/orientation-solver.md
│   ├── testplan/plan-de-tests.md
│   └── architecture.md
├── src/xyzac/
│   ├── geometry_core/        types.py, brep.py, sphere.py, voxelize.py,
│   │                         healing.py, curvature.py
│   ├── machine_model/        machine.py, setup.py, geometry.py
│   ├── tool_model/           assembly.py
│   ├── stock_engine/         stock.py, material.py
│   ├── feature_engine/       revolution.py
│   ├── accessibility_solver/ solver.py            ← différenciateur (1/2)
│   ├── orientation_solver/   solver.py            ← différenciateur (2/2)
│   ├── collision_engine/     field.py, tool_collision.py, spatial.py,
│   │                         machine_guard.py, sweep.py, exact_gouge.py
│   ├── kinematics_solver/    solver.py, compensation.py
│   ├── simulation_engine/    scene.py, validator.py
│   ├── turning_engine/       interfaces.py, profile.py
│   ├── safety_state_machine/ machine.py
│   ├── subtractive_slicer/   interfaces.py, slicer.py, finishing.py
│   ├── strategy_planner/     interfaces.py, planner.py
│   ├── vision_service/       interfaces.py        ← stub M1
│   ├── probing_service/      interfaces.py, fitting.py, simulator.py
│   ├── postprocessor_linuxcnc/ interfaces.py, emit.py
│   ├── linuxcnc_gateway/     interfaces.py, config.py, deposit.py
│   │                         ← fabrique un FICHIER, n'ouvre aucun transport
│   ├── recipe_profiles/      interfaces.py, recipes.py
│   ├── assembly_calibration/ interfaces.py, procedures.py, record.py
│   └── ui/                   render.py,
│                             debug/ palette.py, state.py, scene.py,
│                                    window.py, app.py   ← banc de debug
├── tests/         conftest, 18 fichiers, corpus/ (20 STEP sains + 3 dégradés)
├── tools/         make_corpus.py, make_degraded_corpus.py,
│               demo_vertical_slice.py, demo_m2_pipeline.py,
│               demo_m3_pipeline.py, demo_m7_calibration.py,
│               demo_m9_linuxcnc.py
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
   (`socket`, `telnetlib`, `serial`, `linuxcnc`). Au jalon M9 il ne s'en sert
   toujours pas : il écrit des fichiers. Un test vérifie qu'**aucun** module
   du projet, passerelle incluse, n'importe le binding Python `linuxcnc`.
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

## 9. Ajouts du jalon M7

### machine_model/geometry

```python
MachineGeometry.nominal(machine_id) -> MachineGeometry          # measured=False
MachineGeometry.real_rotation(a_deg, c_deg) -> ndarray          # axes MESURES
MachineGeometry.real_part_to_machine(machine, p_part, a, c) -> ndarray
MachineGeometry.linear_matrix() -> ndarray                      # équerrage + échelle
MachineGeometry.position_uncertainty_mm(reach_mm, worst_case=True) -> float
```

`measured=False` signifie **« aucune mesure »** et non « erreurs nulles ».
`position_uncertainty_mm` **lève** dans cet état : lire des zéros reviendrait à
croire une machine parfaite, ce qui est l'erreur que six jalons de marges
géométriques ont rendue facile.

### kinematics_solver/compensation

```python
solve_real_orientation(geom, d_target, a_seed, c_seed) -> (a, c, résidu, ok, n)
compensate_pose(machine, geom, p_part, d_part, *, a_nominal, c_nominal, ...)
    -> CompensatedMove
realised_pose(machine, geom, move, *, work_offset) -> (point_pièce, axe_outil)
```

La position se corrige **exactement** (les axes linéaires sont une translation
dans le repère machine) ; l'orientation par re-résolution sur les axes mesurés.
Les valeurs nominales sont **exigées** en entrée parce que l'amorce choisit
entre deux solutions séparées de 180° de plateau, et que ce choix est une
décision de trajectoire.

`realised_pose` existe pour les tests : compenser, puis rejouer la cinématique
réelle sur la commande produite, et comparer à la cible.

### probing_service

```python
fit_sphere(points) -> SphereFit                    # refuse une seule latitude
fit_circle_3d(points) -> (centre, normale, rayon, résidu)
fit_plane_normal(points) -> (normale, résidu)      # refuse des points colinéaires
fit_axis_from_rotation(centres, angles, p_nom, u_nom) -> AxisFit
ProbeSimulator(machine, geometry, noise_mm, seed)  # palpeur sur le jumeau
```

Les ajustements **refusent** les configurations dégénérées au lieu de rendre un
nombre qui ressemble à une mesure. Les incertitudes d'`AxisFit` viennent d'un
**jackknife**, qui voit l'étendue angulaire réelle — 160° pour C, 80° pour A —
que les formules fermées ignorent.

Le palpeur simulé rend des **coordonnées d'axes**, pas des positions
euclidiennes idéales : sans cela le jumeau ne porterait aucun défaut du trièdre
linéaire.

### assembly_calibration

```python
calibrate_on_twin(machine, true_geometry, ...) -> (CalibrationReport, MachineGeometry)
record_from_report(machine_id, geometry, report) -> CalibrationRecord
HARDWARE_ONLY: frozenset[CalibrationStep]          # 5 étapes, jamais simulées
```

`true_geometry` est la machine réelle que le jumeau simule ; la procédure ne la
lit jamais, elle ne fait que palper à travers elle. La géométrie rendue est
construite **à partir des mesures**, jamais recopiée.

`CalibrationRecord` distingue trois états qu'il ne faut pas confondre :
`geometry.measured` (la cinématique n'est plus provisoire), `geometry_complete`
(les étapes non matérielles sont faites), `qualified` (pièce d'épreuve mesurée).
`tolerance_statement()` est le **seul endroit du projet autorisé à énoncer une
précision**, et il refuse tant que `qualified` est faux.

### postprocessor_linuxcnc

```python
post_process(plan, safety, current_setup_hash, calibration, *, feed_mm_min)
    -> (gcode: str, EmitReport)
parse_poses(gcode) -> list[dict]
```

Trois gardes, dans cet ordre — et l'ordre est testé : la porte de sécurité,
puis la géométrie mesurée, puis la correspondance du dossier de calibration avec
celui de l'approbation.

L'en-tête porte l'énoncé de tolérance mot pour mot, le budget géométrique, et
les manques (avances non qualifiées, approche et dégagement non générés).

`parse_poses` sert à l'**aller-retour** : un émetteur vérifié contre son propre
calcul ne vérifie rien.

`linuxcnc_gateway` reste verrouillé : poster exige une géométrie mesurée,
envoyer exige une machine qualifiée.

## 10. Ajouts du jalon M8

### recipe_profiles/recipes

```python
MATERIALS: dict[str, MaterialData]         # 6 matières, chacune avec sa SOURCE
build_recipe(material, tool, *, depth_of_cut_mm, width_of_cut_mm,
             machine, derating=None, vc_tolerance=0.25) -> CuttingRecipe
effective_diameter(tool, depth_of_cut_mm) -> float
radial_chip_thinning(diameter_mm, width_of_cut_mm) -> float
```

Une matière inconnue **lève** (`UnknownMaterialError`) plutôt que de retomber
sur des paramètres d'aluminium. Le déclassement par défaut est de 0,5 et il est
**appliqué**, pas seulement conseillé : une note disant « commencer nettement
en dessous » ne protège personne si le code livre quand même les valeurs de
table.

Le diamètre effectif d'une hémisphérique à faible profondeur
(`2·√(D·ap − ap²)`, soit 2,15 mm pour une D6 à ap = 0,2) est ce qui sépare une
vitesse de coupe calculée d'une vitesse de coupe réelle. `CuttingRecipe` porte
`clamped`, `warnings`, `derating`, et `qualified = False` — jamais autre chose.

### subtractive_slicer + strategy_planner

```python
with_approach_retract(points, is_rapid, direction, clearance_z, frame,
                      *, standoff_mm=2.0, plunge_feed=True)
```

Les opérations d'ébauche portent désormais `continuous_path` : le chemin
**complet**, liaisons et approches comprises, avec son masque de rapides. Ce
qui est posté est exactement ce qui a été validé au balayage — l'opération ne
portait auparavant que les points de coupe.

`post_process` exige maintenant une `recipe` : il n'existe plus de
`feed_mm_min` par défaut, et l'en-tête porte la provenance de la recette et ses
avertissements. La ligne annonçant l'absence d'approche est **calculée** depuis
les trajectoires, plus écrite.

## 11. Ajouts du jalon M9 — la frontière LinuxCNC

### linuxcnc_gateway/config

```python
KINEMATICS_MODULE = "xyzac-trt-kins"       # module intégré, pas trivkins
build_config(machine, calibration=None, *, name, servo_period_ns) -> ConfigFiles
ConfigFiles.write(directory) -> list[str]  # .ini, .hal, postgui.hal, .tbl
ConfigFiles.describe() -> str
verification_command(directory) -> str
```

La configuration est **dérivée** de `MachineKinematics` et du
`CalibrationRecord`, jamais saisie : une course tapée à la main dans un INI est
une deuxième source de vérité qui divergera. Chaque valeur émise porte un des
trois degrés de confiance — mesurée, dérivée du modèle, ou **provisoire** — et
`to_verify` / `provisional` listent nommément ce qui reste à confirmer sur la
machine.

Le point dangereux est nommé comme tel dans le fichier : le **signe** des
offsets de pivot ne provoque aucun échec au démarrage, seulement un usinage
faux, et seule l'étape matérielle `AXIS_DIRECTION` l'établit. Prise d'origine
et table d'outils sont laissées vides **avec leur motif écrit dedans**, plutôt
que remplies d'une valeur plausible.

### linuxcnc_gateway/deposit

```python
deposit_program(gcode, directory, *, target, safety, setup_hash,
                calibration, filename="", journal=None) -> DepositRecord
start_cycle(*args, **kw)                   # NotImplementedError, par décision
```

Quatre conditions, dans cet ordre : approbation de sécurité vivante, hash de
montage identique, géométrie mesurée, puis — **pour la cible HARDWARE
seulement** — machine qualifiée. La simulation reste ouverte : la conditionner
à la qualification ferait une porte qui se verrouille sur sa propre clé, car la
pièce d'épreuve doit être simulée avant d'être usinée.

Ce qui traverse la frontière est **un fichier, et rien d'autre**. Aucun
lancement de cycle n'existe, et son absence est une décision inscrite dans le
code plutôt qu'un manque : ce jalon ne produit pas de mouvement, il produit de
quoi en produire un le jour où une machine qualifiée existera.

La configuration **a été chargée par LinuxCNC 2.9** (compilé depuis sa source,
mode `uspace`). Elle démarre, et l'épreuve a révélé cinq défauts dont deux
silencieux : `x-offset` n'est pas lue par la cinématique xyzac, `y-offset` porte
l'écart A↔C et non une position absolue, et l'INI n'avait aucune section
`[HAL]` — les deux fichiers HAL étaient écrits et jamais chargés. Voir
[la note de validation](validation-linuxcnc.md).

Le recoupement a ensuite été poussé jusqu'à l'exécution : `part_to_machine_point`
et `xyzacKinematicsInverse` s'accordent à **7,1·10⁻¹⁵ mm** contre la fonction
compilée, et à **1,4·10⁻¹⁴ mm** sur LinuxCNC **en marche** (56 poses commandées
en MDI, articulations relues) — `tools/verify_kinematics_linuxcnc.py`, trois
étages.

Cette dernière étape a exigé de corriger un septième défaut : `[EMCIO]EMCIO`
manquait, et la tâche décide d'employer le contrôleur d'entrées-sorties sur la
**seule présence de cette clé** alors que le script de démarrage a sa propre
valeur par défaut. `io` tournait donc, ses broches répondaient, et la machine
ne pouvait jamais être mise en marche — sans un seul message d'erreur.

Ce que rien de cela ne dit : le **signe** des offsets.
`verification_command()` donne la commande à passer sur la machine de
l'utilisateur.


## 12. Ajouts du jalon M10 — décider une passe complète

### accessibility_solver : vérifier au lieu d'explorer

```python
AccessibilitySolver.verify_direction(contacts, normals, direction,
                                     *, block=16, allow_singular=True,
                                     with_clearance=False) -> DirectionVerdict
```

`AccessibilityMap` décrit **toutes les orientations en un point** ;
`DirectionVerdict` décrit **une orientation en tous les points**. Les deux sont
nécessaires : l'un pour découvrir, l'autre pour conclure. Découvrir coûte
65 ms/pt, conclure 1,6 ms/pt.

`block` est un réglage de **coût** : le préfiltre d'obstacles se rabat sur une
sphère de rayon « portée + étendue du bloc », donc à 256 la vérification est
aussi lente que le champ complet. Un test exige que le verdict soit invariant.

`min_margin()` porte dans sa documentation la raison de sa propre inutilité :
l'arête de coupe est tangente par construction. `min_clearance()` est la marge
qui répond à « le porte-outil est-il passé loin ? ».

### strategy_planner/indexed_pass

```python
decide_indexed_pass(solver, points, normals, *, n_probe=24,
                    max_candidates=6) -> IndexedPassVerdict
```

Sondage réparti → candidats par intersection → vérification de chaque candidat
sur la passe **entière**. On retient celui dont le dégagement **minimal** est le
plus grand, pas le premier qui passe.

`IndexedPassVerdict.basis` dit sur quoi la conclusion repose — `verification`,
`contre-exemple` ou `intersection-vide` — et `conclusive` porte la réserve qui
va avec : les négatifs épuisent une **grille** de 642 directions, donc ils
valent à sa résolution. Le positif, lui, exhibe une orientation.

`plan_finishing(..., verify=True)` n'émet **aucune opération** pour une passe
non indexable : la trajectoire simultanée n'est pas devenue abordable, et
émettre une opération laisserait croire le contraire.

## 13. Ajouts du jalon M11 — ordonnancer les montages

### strategy_planner/setups

```python
derive_mount(bbox_lo, bbox_hi, *, riser_mm=25.0) -> (dx, dy, dz)
CANONICAL_MOUNTS: tuple[PartOrientation, ...]          # SIX, pas vingt-quatre
ideal_machine(machine) -> MachineKinematics            # sans butees ni organes
screen_orientation(orientation, passes, field, make_solver, machine, tool,
                   *, probe_tool=None, bbox_lo, bbox_hi, n_probe=8)
plan_setups(passes, field, make_solver, machine, tool, *, probe_tool=None, ...)
    -> SetupPlan
```

Un remontage est une **rotation du repère pièce** : le champ d'obstacles ne
contient que pièce, brut et bridages — tout ce qui tourne avec la pièce — donc
il suffit de le faire tourner. Aucune modification du solveur.

**Six candidats.** L'axe C étant continu, deux poses qui ne diffèrent que par
une rotation autour du Z du montage sont la même pose. C'est la cinématique qui
réduit l'espace de recherche.

`ideal_machine` est le discriminant : si un point échoue même sans butées ni
organes, aucun montage n'y changera rien. Et `probe_conclusive` refuse de
conclure quand le bec de sondage ne dépasse pas le gonflement du champ — le
test discret ne décide pas au-dessous de sa propre marge (ADR-001 / D2).

`SetupPlan.tolerance_warning()` refuse d'annoncer un chiffre dès qu'il y a plus
d'un montage : chaque remontage reréférence la pièce et les budgets se
composent, ce que le moteur ne sait pas encore modéliser.

`derive_mount` vivait dans `ui/debug/state.py` — de la logique métier dans
l'interface, ce que la règle de dépendance interdit. L'interface délègue
désormais.
