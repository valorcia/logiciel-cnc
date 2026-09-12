# Plan de tests — jalon M1

## 1. Principe

Un test qui vérifie seulement que « ça n'a pas planté » ne protège de rien. Le
corpus est donc **généré** (`tools/make_corpus.py`) plutôt que collecté, ce qui
donne trois propriétés :

- **vérité terrain calculable** : volume, nombre de faces, axes de révolution
  sont connus analytiquement — un test peut affirmer une valeur ;
- **reproductible** : aucun binaire opaque au dépôt, aucune licence tierce ;
- **paramétrable** : on peut resserrer une cote jusqu'à faire échouer le
  solveur, et donc **mesurer sa limite** au lieu de la supposer.

## 2. Les 20 géométries STEP synthétiques

Chaque pièce cible **une** difficulté identifiée du moteur.

| ID | Nom | Difficulté visée | Comportement attendu |
|---|---|---|---|
| C01 | bloc_simple | référence | import et volume exacts ; 6 faces planes |
| C02 | poche_droite | poche fermée | parois verticales accessibles à A = 0 |
| C03 | poche_conique | normale variable | lead continu sur la face conique |
| C04 | rainure_profonde | collision porte-outil | rejet `COLLISION_HOLDER` en vertical ; admissible en basculant |
| C05 | ailettes_rapprochées | accès bilatéral contraint | cônes d'accessibilité étroits |
| C06 | contre_dépouille | contre-dépouille | aucune direction à A = 0 ; exige \|A\| > 0 |
| C07 | gorge_en_T | contre-dépouille double | inaccessible sans outil à col ; doit proposer le remède |
| C08 | trou_incliné | indexation 3+2 | un seul couple (A, C) couvre tout |
| C09 | trous_4_faces | multi-indexation | 4 segments 3+2 distincts, aucun simultané |
| C10 | dôme_convexe | 5 axes simultané | intersection des admissibles vide → simultané justifié |
| C11 | cavité_sphérique | normales rentrantes | pas de gouge du corps d'outil |
| C12 | arbre_étagé | révolution coaxiale C | détection de révolution ; candidat tournage |
| C13 | arbre_gorge_torique | révolution + concave | révolution détectée malgré le tore |
| C14 | hybride_méplats | hybride tournage/fraisage | régions de révolution **et** prismatiques séparées |
| C15 | révolution_hors_axe | **faux positif tournage** | révolution détectée mais **rejetée** (axe non colinéaire à C) |
| C16 | paroi_mince | rigidité | l'orientation doit pénaliser les grands porte-à-faux |
| C17 | face_quasi_horizontale | singularité A → 0 | rejet `SINGULARITY` ; pas de retournement C |
| C18 | poche_fond_bombé | types de surface mélangés | plan + cylindre + sphère sur la même pièce |
| C19 | deux_solides | topologie compound | import sans erreur ; 2 solides comptés |
| C20 | micro_détail | tolérances | le perçage D1,2 survit à la tessellation |

Régénération : `python tools/make_corpus.py`. Le manifeste
(`tests/corpus/manifest.json`) fige volume, nombre de faces, solides, types de
surface et boîte englobante — toute dérive d'OCCT, de tolérance ou d'unités est
détectée.

## 3. Suites de tests

### `test_geometry_core.py` — invariants du noyau

| Test | Ce qu'il protège |
|---|---|
| `transform_inverse_is_identity` | algèbre des repères |
| `unwrap_keeps_continuity_across_pi` | sans ça, retournement de plateau à ±180° |
| `angle_between_is_stable_at_extremes` | `atan2(\|cross\|, dot)` et non `acos(dot)` |
| `icosphere_counts_and_unit_norm` | 12/42/162/642 directions |
| `connected_components_separates_disjoint_caps` | cônes d'accessibilité |
| **`sample_surface_respects_spacing_bound`** | **l'hypothèse dont dépend TOUT le moteur de collision** |
| `sampled_normals_point_outward` | une normale rentrante inverse le sens d'approche |

### `test_kinematics.py` — la cinématique XYZAC

| Test | Ce qu'il protège |
|---|---|
| **`forward_kinematics_maps_tool_axis_to_machine_z`** | `R·d = +Z` sur 500 couples : **l'identité fondatrice** |
| `ik_fk_round_trip_on_random_directions` | 400 directions × 2 branches, résidu < 1e-6° |
| `ik_always_returns_two_branches` | oublier une branche = déclarer inaccessible ce qui l'est |
| `asymmetric_a_travel_selects_mirror_branch` | berceau [−120°, +30°] |
| `singularity_severity_peaks_at_zero` | |
| `conditioning_explodes_near_zero` | 1/\|sin A\| : 57× à A = 1° |
| `pivot_offsets_affect_machine_coordinates` | ignorer les pivots = simulation juste, pièce fausse |

### `test_tool_and_collision.py` — outil complet et collisions

| Test | Ce qu'il protège |
|---|---|
| `tool_stack_must_be_contiguous` | un trou dans la pile rend un morceau d'outil invisible |
| `gauge_beyond_modelled_stack_is_refused` | nez de broche non modélisé = fausse absence de collision |
| `full_tool_is_modelled_up_to_spindle_nose` | **sans nez de broche, le différenciateur n'existe pas** |
| `signed_clearance_on_cylinder` | 5 cas analytiques |
| `holder_collision_is_named_not_just_detected` | l'UI doit pouvoir proposer un remède |
| `cutting_edge_may_enter_stock_but_not_fixture` | la règle physique du moteur |
| **`vectorized_matches_reference_loop`** | **test différentiel** : protège des optimisations divergentes |
| `per_direction_tcp_is_honoured` | un TCP unique fausse la réponse d'un rayon d'outil |

### `test_corpus_regression.py` — les 20 géométries

- import + topologie stables (20 cas) ;
- tessellation et échantillonnage valides, normales unitaires (20 cas) ;
- unités en millimètres ;
- micro-détail préservé (C20) ; compound à 2 solides (C19) ;
- **détection de révolution et rejet du faux positif** (C12, C13, C14, C15, C01) ;
- axe du tore extrait (C13).

### `test_solvers.py` — les deux solveurs

- TCP : bout droit vs hémisphérique ;
- filtres face-arrière, lead, singularité ;
- **chaque rejet porte un remède** ;
- cônes d'accessibilité cohérents ;
- **bornes E3 jamais en désaccord avec le test exact** ;
- **plan déterministe** (même entrée → même sortie) ;
- **pas de retournement de plateau** ;
- **une face plane accessible se couvre en 3+2** (> 90 %) ;
- un plan incomplet le dit et nomme les points.

### `test_safety.py` — les interdictions

| Test | Ce qu'il rend impossible |
|---|---|
| `gates_cannot_be_skipped` | approuver sans collision/cinématique/simulation |
| `approval_requires_a_named_operator` | approbation anonyme |
| `failed_gate_leads_to_fault_not_approval` | continuer après échec de porte |
| **`setup_change_invalidates_approval`** | **rejouer un programme sous un autre setup** |
| `postprocessor_refuses_without_approval` | générer du G-code sans approbation |
| `postprocessor_is_not_implemented_even_when_approved` | verrou ADR-001 §6 |
| `gateway_refuses_to_connect_at_this_milestone` | toucher une machine réelle |
| `cosmetic_change_does_not_invalidate` | invalidations parasites (un commentaire) |
| `geometric_change_invalidates` (5 mutations) | origine, surépaisseur, bridage, jauge, pivot |
| **`no_module_besides_gateway_imports_a_machine_transport`** | **vérifié sur le source**, pas seulement documenté |

## 4. Suites ajoutées au jalon M2

### `test_m2_spatial_material.py` — index, voxelisation, matière

| Test | Ce qu'il protège |
|---|---|
| `grid_query_matches_brute_force` (4 rayons) | l'index ne change **jamais** l'ensemble retourné, seulement le coût |
| `grid_capsule_matches_brute_force` | idem pour la requête du balayage |
| `obstacle_field_subset_identical_with_and_without_index` | le choix de stratégie est une optimisation, pas une sémantique |
| `voxel_volume_is_exact_on_a_box` | une dérive ici = erreur de parité du lancer de rayons |
| `voxel_volume_converges_on_curved_solids` (3 cas) | l'écart reste de l'ordre de la discrétisation (< 3 % à 0,8 mm) |
| `voxelization_handles_two_disjoint_solids` | le vide entre deux solides n'est pas rempli |
| **`part_is_protected_and_never_removed`** | **masquer une gouge en la retirant du suivi serait le pire comportement** |
| `carve_to_finished_leaves_only_the_protected_part` | |
| `boundary_points_are_conservative` | le rayon couvre le demi-diagonal du voxel |

### `test_m2_validation.py` — garde machine, balayage, validation, gouge exacte

| Test | Ce qu'il protège |
|---|---|
| `machine_volumes_move_with_the_cradle` | traiter le berceau comme statique rendrait le garde aveugle |
| `guard_detects_collision_with_the_cradle` / `..._linear_travel_violation` | deux causes, deux remèdes |
| `guard_check_many_matches_check_pose` | test différentiel du chemin groupé |
| `sweep_bound_grows_with_rotation` | 30° de rotation > 60 mm de déplacement |
| **`sweep_catches_what_both_endpoints_miss`** | **LE test du jalon** : deux poses saines, un chemin qui ne l'est pas |
| `sweep_interpolates_axes_not_directions` | le contrôleur interpole les axes ; c'est son mouvement qui fait foi |
| `sweep_unwraps_c_across_the_seam` | sinon on balaie un tour de plateau qui n'existe pas |
| `validator_runs_all_four_checks` | poses, cinématique, machine, balayage |
| `validator_reports_every_defect_not_just_the_first` | éviter la boucle corriger-relancer |
| `singularity_is_a_warning_not_an_error` | elle dégrade, elle ne casse pas |
| **`simulation_gate_cannot_be_passed_without_validating`** | **l'état « simulé » exige une validation réelle** |
| **`exact_verifier_detects_a_five_hundredth_gouge`** | **0,05 mm — ce que le nuage à 2 mm ne peut pas voir** |
| `exact_verifier_accepts_tangential_contact` | en fraisage la coupe est tangente par construction |
| `sparse_verification_is_documented_as_a_sample` | un sondage n'est pas une preuve |

### Ajouts à `test_solvers.py`

- `seeds_can_only_enlarge_the_admissible_set` — propriété garantie ;
- `seeds_recover_directions_the_uniform_grid_misses` — la normale exacte est
  toujours évaluée, la solution ne dépend pas d'un alignement fortuit ;
- `machine_guard_rejects_a_part_sitting_on_the_table` ;
- **`indexed_segment_is_verified_exactly_not_just_proposed`** ;
- `indexed_segment_falls_back_when_verification_refuses` — jamais indexé sur
  une orientation non vérifiée ;
- `refinement_respects_machine_limits` ;
- `refinement_does_not_blow_up_rotary_travel` — borne l'augmentation de course
  A+C, après avoir mesuré un +59° pour +0,26 mm de marge.

## 5. Suites ajoutées au jalon M3

### Corpus DÉGRADÉ — `tests/corpus/step_degraded/`

Le corpus principal est généré par OCCT : cousu, orienté, aux tolérances par
défaut. Il ne prouve donc rien sur la robustesse à un fichier venu d'ailleurs.
Ces cas ne se collectent pas facilement (licences, confidentialité) : on les
**fabrique**, ce qui a l'avantage de connaître exactement le défaut injecté.

| ID | Défaut injecté | Comportement attendu |
|---|---|---|
| D01 | pavé privé d'une face (shell ouvert) | détecté par l'absence de solide, **refusé** |
| D02 | pièce en pouces lue en mm (×1/25,4) | alerte de plausibilité, **pas** de réparation |
| D03 | pièce de 2,5 m | alerte de plausibilité, **pas** de réparation |

Génération : `python tools/make_degraded_corpus.py`.

### `test_m3_slicer_planner.py`

| Test | Ce qu'il protège |
|---|---|
| **`finish_allowance_is_independent_of_grid_pitch`** (3 pas) | une surépaisseur de 0,2 mm devenait 1,5 / 1,0 / 0,6 mm selon le pas |
| `reachability_is_direction_dependent_and_sensible` | une poche ouverte en haut se voit d'en haut |
| `protected_material_blocks_rays_but_removable_does_not` | compter le brut comme obstacle déclarerait tout inaccessible |
| `disc_covers_diagonals_that_the_l1_ball_misses` | la dilatation 4-connexe donne un losange PLUS PETIT que le disque |
| **`roughing_never_gouges_the_protected_part`** | **le slicer peut laisser de la matière, jamais entamer la pièce** |
| `grid_extends_beyond_the_stock_for_profiling` | pour profiler un flanc, le centre d'outil est HORS du brut |
| **`link_moves_are_explicit_and_flagged`** | **sans liaisons, le validateur relie en ligne droite — à travers la matière** |
| `link_moves_are_sparse` | densifier les liaisons gonflait le programme de 94 % de points inutiles |
| **`vertical_indexation_is_a_valid_candidate`** | **la singularité gêne le MOUVEMENT, pas l'indexation** |
| `candidates_are_filtered_by_machine_travel` | −Z demande A = 180° : hors courses, donc pas proposé |
| `greedy_plan_covers_most_of_the_material` | + aucun voxel gougé |
| `plan_report_keeps_the_full_candidate_list` | la liste était vidée pendant la boucle, faussant le bilan |
| **`fixtures_are_protected_material`** | **sinon le slicer planifie des passes dans l'étau** |
| `open_shell_is_detected_and_refused` | un shell ouvert est « valide » et OCCT lui calcule un volume |
| `unit_confusion_is_flagged_as_plausibility_not_defect` | ne pas lancer ShapeFix sur une pièce intacte |
| `healing_refuses_to_change_the_part` | une réparation qui déplace la matière n'est pas une réparation |

## 6. État actuel

```
$ python -m pytest tests/ -q
182 passed
```

Cinq défauts réels ont été trouvés **par ces tests** pendant le développement,
ce qui est leur meilleure justification. Les trois premiers datent de M1 :

1. **Triangles dégénérés** (C11) : OCCT produit des triangles d'aire nulle sur
   les surfaces sphériques. Leur normale, normalisée par 1,0, devenait un
   vecteur quasi nul qui *passait* pour une normale — et le filtre géométrique
   du solveur aurait rendu un résultat arbitraire sur ces points. Corrigé en
   écartant explicitement ces triangles.
2. **Borne inférieure invalide** : elle rejetait 78 directions là où le test
   exact en validait 7, parce qu'elle n'appliquait pas les mêmes exemptions.
   Corrigé en la restreignant aux couples sans exemption.

Un troisième défaut, de modélisation, a été trouvé en écrivant les tests
d'orientation : le **bec** de l'outil (rayon de bec / hémisphérique) n'existait
que dans le calcul du TCP, pas dans la géométrie de collision. Une fraise
hémisphérique se comportait donc comme une fraise à bout droit et voyait son
talon déclaré en gouge dès qu'on l'inclinait — c'est-à-dire dans tous les cas où
l'on se sert d'une hémisphérique. Le bec est désormais modélisé par 8 troncs de
cône (écart au cercle exact ≈ 0,015 mm pour un bec de 3 mm).

Deux autres au jalon M2 :

4. **Raffinement hors course.** Le vérificateur de pose ne connaissait que la
   pièce. Le raffinement a gagné 0,24 mm de marge en poussant l'axe Z à 60,1 mm
   pour une course s'arrêtant à 60,0 : meilleur sur le critère optimisé,
   irréalisable sur la machine. D'où `make_pose_verifier`, qui vérifie les deux.
5. **Segmentation 3+2 non vérifiée.** Les germes analytiques n'étant pas des
   sommets de grille, l'intersection d'ensembles est devenue une heuristique.
   Un segment pouvait donc être déclaré indexable sur une orientation ne
   dégageant pas partout. Corrigé par une vérification exacte en chaque point.
6. **Raffinement optimisant un proxy.** Son score ne pénalisait que l'écart
   entre directions voisines : +0,26 mm de marge obtenus en portant la course
   A+C de 86 à 145°. Deux directions proches sur la sphère peuvent demander des
   couples (A, C) très éloignés. Le score porte désormais sur la course réelle.

Les défauts 4 et 6 relèvent de la même erreur — **optimiser un proxy au lieu du
critère réel** — ce qui en fait un point de vigilance permanent plutôt qu'un
incident isolé.

Six de plus au jalon M3, dont plusieurs n'auraient pas été trouvés sans la
simulation d'enlèvement de matière :

7. **Surépaisseur pilotée par le pas de grille** : 0,2 mm demandés devenaient
   1,5 mm. Un paramètre utilisateur décidé par un réglage numérique sans rapport.
8. **Dilatation en losange** : la boule L1 est plus PETITE que le disque dans les
   diagonales. Appliquée à la zone interdite, elle autorisait des gouges.
9. **Marge de cellule manquante** : une dilatation ne marque que les cellules
   dont le centre est à moins de R, alors qu'un centre d'outil peut être partout
   dans sa cellule. 108 poses sur 3 428 touchaient la paroi.
10. **Grille calée sur le brut** : pas de cellule pour poser le centre d'outil
    hors matière, donc aucun profilage de flanc — 8 000 mm³ jamais touchés.
11. **Liaisons implicites** : le zigzag émettait des segments isolés, et le
    validateur les reliait à travers la pièce. Les collisions étaient réelles.
12. **Bridages invisibles au slicer** : des passes planifiées dans l'étau.

Le point commun des défauts 8, 9 et du désaccord slicer/validateur (0,226 mm sur
une pose sur 270) : **deux modèles conservatifs indépendants divergent s'ils ne
partagent pas leurs marges.** C'est désormais vérifié par construction — le
validateur refuse un tranchage qui n'a pas employé la même clearance.

## 7. Ce qui n'est PAS testé, et doit l'être

| Manque | État |
|---|---|
| ~~Collision sur le balayage~~ | **levé M2** |
| ~~Volumes machine~~ | **levé M2** |
| ~~Suivi de matière enlevée~~ | **levé M2** |
| ~~Import de STEP dégradés~~ | **levé M3** (corpus D01–D03) |
| ~~Gamme complète~~ | **levé M3** (ébauche indexée validée) |
| Gouge fine sur **toute** la passe (aujourd'hui : sondage épars) | M4 |
| Performance sur le matériel cible (Pi 5) — **jamais mesurée** | M4 |
| Finition : contour-parallèle, passes 5 axes simultanées | M4 |
| Tournage : génération de trajectoires | M4/M5 |
| Poids d'orientation calibrés | exige une machine |
| Tout ce qui touche une machine réelle | après qualification |

## 8. Précision — ce que les tests ne disent pas

Aucun test de ce dépôt ne dit quoi que ce soit de la précision d'une pièce
usinée. Ils portent sur la **justesse numérique** du moteur.

**±0,02 mm n'est pas un acquis.** C'est un objectif de qualification physique, à
démontrer sur pièce d'épreuve usinée **puis mesurée**, machine par machine,
après calibration d'assemblage. Le logiciel ne peut garantir que sa propre
erreur numérique ; il ne peut rien garantir de la chaîne mécanique d'un kit
assemblé par l'acheteur.

`CalibrationReport.precision_statement()` renvoie explicitement
« Précision NON QUALIFIÉE » tant que la pièce d'épreuve n'a pas été mesurée.
Aucune documentation ni interface ne doit annoncer un chiffre que cette méthode
ne renvoie pas.
