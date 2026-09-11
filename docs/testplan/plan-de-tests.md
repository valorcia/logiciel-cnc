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

## 4. État actuel

```
$ python -m pytest tests/ -q
108 passed
```

Deux bugs réels ont été trouvés **par ces tests** pendant le développement du
jalon, ce qui est leur meilleure justification :

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

## 5. Ce qui n'est PAS testé, et doit l'être

| Manque | Jalon |
|---|---|
| Collision sur le **balayage** entre deux points (on teste les positions, pas les transitions) | M2 — **bloquant pour toute validation de trajectoire** |
| Volumes de collision machine (berceau, plateau) dans le champ d'obstacles | M2 |
| Détection de gouge fine de l'arête (requêtes exactes B-Rep) | M3 |
| Suivi de matière enlevée (le brut est traité comme intact) | M2 |
| Performance sur le matériel cible (Pi 5) — **jamais mesurée** | M2 |
| Import de STEP réels (mal cousus, tolérances hétérogènes, unités en pouces) | M2 |
| Tout ce qui touche une machine réelle | après M3 |

## 6. Précision — ce que les tests ne disent pas

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
