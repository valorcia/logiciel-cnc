# Slicer soustractif XYZAC

Moteur de fabrication soustractive 5 axes pour un centre d'usinage maker
**XYZAC** vendu en kit. L'utilisateur importe un STEP, définit un brut, et la
machine calcule seule comment enlever le volume `brut \ pièce`.

Ce n'est **pas** un CAM généraliste : l'utilisateur ne programme pas
d'opérations. Ce n'est **pas** un portage d'OrcaSlicer : l'inspiration est
l'expérience utilisateur des slicers 3D, le moteur est propre et soustractif.

> **État : jalon M6.** Ébauche indexée, finition à crête contrôlée — le pas
> venant de la **courbure locale mesurée** et non d'une formule plane — et
> tournage sur l'axe C : profil de révolution, ovalité robuste, passes, corps
> de l'outil vérifié, refus motivé. En 3+2 ou en 5 axes simultané selon ce que
> la géométrie permet. La gouge du porte-outil est **prouvée sur toute la
> passe**, et non sondée. Aucun G-code n'est généré : le verrou tient, et son
> motif n'est pas logiciel — **la machine n'est pas calibrée**. Voir
> [ADR-001 §6](docs/adr/ADR-001-architecture-fondatrice.md),
> [ADR-002](docs/adr/ADR-002-jalon-M2.md),
> [ADR-003](docs/adr/ADR-003-jalon-M3.md),
> [ADR-004](docs/adr/ADR-004-jalon-M4.md),
> [ADR-005](docs/adr/ADR-005-jalon-M5.md),
> [ADR-006](docs/adr/ADR-006-jalon-M6.md).

---

## Le différenciateur

Pour chaque trajectoire, l'orientation 5 axes est calculée en modélisant
**l'outil complet** — bec, arête de coupe, col, tige, porte-outil, **nez de
broche** — et pas seulement le point TCP.

Le moteur cherche les orientations sans collision compatibles XYZAC, puis
optimise une **séquence A/C** continue, stable, rigide et éloignée des
singularités. Il utilise **3+2 quand c'est possible** et le simultané
**uniquement quand la géométrie l'impose** — cette bascule est *dérivée* de
l'intersection des ensembles admissibles, pas réglée à la main.

Un rejet n'est jamais un échec muet : il nomme le tronçon fautif et propose un
remède (« le porte-outil touche → allonge la jauge »).

---

## Démarrage

```bash
pip install -e ".[viz,dev]"

python tools/make_corpus.py                  # 20 géométries STEP synthétiques
python tools/make_degraded_corpus.py         # 3 STEP volontairement abîmés
python -m pytest tests/ -q                   # 246 tests

# M1 — accessibilité + orientation + visualisation
python tools/demo_vertical_slice.py C08
python tools/demo_vertical_slice.py C10 --ballnose --face 6   # 5 axes simultané

# M2 — pipeline complet jusqu'aux portes de sécurité
python tools/demo_m2_pipeline.py C02 --face 2 --ballnose --material finished

# M3 — STEP -> GAMME -> validation, sans passe écrite à la main
python tools/demo_m3_pipeline.py C02 --max-setups 1
```

Le pipeline M2 enchaîne : scène → accessibilité → orientation (+ vérification
3+2 et raffinement) → **validation 4 points** → portes de sécurité → refus de
générer du G-code.

Le prototype produit quatre images dans `out/` :

| Fichier | Contenu |
|---|---|
| `*_outil.png` | profil de l'outil complet, par tronçon |
| `*_scene.png` | digital twin : brut, pièce, bridages, plateau C, outil placé |
| `*_orientations.png` | directions admissibles / rejetées **par motif**, marges, espace (A, C) |
| `*_sequence_ac.png` | séquence A/C, segments 3+2 vs simultané, marges |

---

## Documentation

| Document | Contenu |
|---|---|
| [ADR-001](docs/adr/ADR-001-architecture-fondatrice.md) | décisions fondatrices, alternatives écartées, risques |
| [Audit dépendances & licences](docs/audit/dependencies-licenses.md) | ce qui est réutilisable, et ce qui ne l'est pas |
| [Architecture](docs/architecture.md) | arborescence, règles de dépendance, interfaces |
| [ADR-002](docs/adr/ADR-002-jalon-M2.md) | jalon M2 : ce qui a levé les limites de M1, et ce qui reste |
| [ADR-003](docs/adr/ADR-003-jalon-M3.md) | jalon M3 : slicer, planificateur de gammes, import réel |
| [ADR-004](docs/adr/ADR-004-jalon-M4.md) | jalon M4 : finition, coût du calcul, cinq défauts de repère |
| [ADR-005](docs/adr/ADR-005-jalon-M5.md) | jalon M5 : courbure locale, tournage, et la rectification d'une erreur de D31 |
| [ADR-006](docs/adr/ADR-006-jalon-M6.md) | jalon M6 : coût du calcul (×5,5), preuve de gouge, corps de l'outil de tour |
| [Accessibility Solver](docs/algorithms/accessibility-solver.md) | algorithme, garantie conservative, performance mesurée |
| [Orientation Solver](docs/algorithms/orientation-solver.md) | Viterbi, segmentation 3+2, raffinement |
| [Plan de tests](docs/testplan/plan-de-tests.md) | 20 géométries, 108 tests, ce qui n'est pas testé |

---

## Ce que produit le moteur

À partir d'un STEP et d'un brut, sans que l'utilisateur programme quoi que ce
soit :

1. **import contrôlé** — diagnostic, réparation seulement si un défaut
   géométrique le justifie, refus si la forme n'a pas d'intérieur ;
2. **suivi de matière** sur grille voxel (la pièce et les bridages sont
   protégés, le reste est à enlever) ;
3. **choix des indexations** par couverture gloutonne du volume atteignable,
   filtrée par les courses A/C ;
4. **tranchage** en couches perpendiculaires à chaque indexation, avec liaisons
   explicites au plan de dégagement ;
5. **validation couche par couche** contre l'état réel de la matière ;
6. **finition** à hauteur de crête contrôlée, en 3+2 ou en 5 axes simultané
   selon ce que la géométrie permet.

Mesures : sur une poche débouchante, 12/12 couches d'ébauche acceptées, marge
minimale 0,700 mm, 52 % du volume enlevé en une seule indexation. Sur un dôme,
la gamme de finition emploie les trois modes — `3+2` sur les faces planes,
`simultané` sur la calotte, et `inaccessible` là où le porte-outil ne passe pas,
en le disant.

Le pas de finition se déduit d'une crête admissible. Sur un plan,
`h = R − √(R² − (s/2)²)` : 10 µm de crête avec un bec R3 donnent 0,489 mm de
pas. Sur une surface courbe cette formule est **optimiste en convexe** — 15,7 µm
réels contre 10,4 prédits sur une bosse de 6 mm — donc le pas se calcule depuis
la courbure locale mesurée sur le B-Rep (forme fermée exacte, `curvature_stepover`).
Cela reste une consigne géométrique, pas une garantie d'état de surface.

## L'axe C est aussi une broche

Le même axe sert d'axe d'indexation en fraisage et de broche de tournage. Le
moteur détecte les régions de révolution, extrait la silhouette `(z, r)` de la
pièce, mesure son défaut de circularité et planifie des passes — ébauche à
rayon décroissant, contour à la surépaisseur, finition.

Le tournage est le seul module à travailler sur une géométrie **exacte** : une
pièce de révolution est entièrement décrite par sa silhouette, donc rien n'y
oblige au test discret conservatif employé partout ailleurs.

Un profil plus raide que le dégagement de l'outil est refusé **avant** toute
génération de passes, en nommant les zones fautives : ce n'est pas un problème
de trajectoire, et aucun recalcul n'y remédie. Le défaut de circularité se
mesure par secteur angulaire et par quantile (P95 − P5), sans quoi un
épaulement passe pour un méplat.

Le basculement indexation ↔ broche continue **n'est pas un réglage** : il
invalide l'approbation de sécurité et exige une nouvelle simulation.

## Ce que la vérification couvre, et ce qu'elle ne couvre pas

Un vérificateur qui se tait doit dire s'il a regardé. C'est la différence entre
un sondage et une preuve, et elle a été mesurée : une pose sur 120 enfoncée de
4 mm dans un bloc — 113 mm³ de gouge — n'est **pas vue** par un sondage à douze
poses, dont le silence ressemble pourtant à un verdict.

`certify_plan_exact` rend donc une preuve sur toute la passe, en deux volets
parce qu'il y a deux physiques :

- **tronçons non coupants** (col, tige, porte-outil, nez de broche) : ils
  doivent garder une distance, donc une majoration du déplacement suffit à
  couvrir tout un intervalle sans rien y calculer. Une passe de 120 poses avec
  20 mm de garde est prouvée en **3 requêtes exactes** ;
- **arête de coupe** : tangente à la surface par construction, donc
  incertifiable par la distance. Vérifiée en **chaque pose**.

Ce qui reste non prouvé est écrit dans le certificat : rien entre deux poses
consécutives pour l'arête, et les intervalles non couverts sortent avec leur
position. Un budget épuisé rend un certificat *incomplet*, jamais optimiste.

## Ce que valide le moteur

Quatre vérifications, toutes exécutées, toutes nécessaires :

| | Vérification | Ce qu'elle attrape |
|---|---|---|
| V1 | **poses** | l'outil complet dégage en chaque point de contact |
| V2 | **cinématique** | butées A/C, singularité, variation rotative excessive |
| V3 | **machine** | berceau, plateau, carters + courses linéaires X/Y/Z |
| V4 | **balayage** | le mouvement **continu** entre poses successives |

V4 est celle qui change tout : V1–V3 portent sur des instants, V4 sur le trajet.
Deux poses saines reliées par un chemin qui ne l'est pas est le mode de
collision le plus courant en 5 axes — et sur le cas du dôme C10, la marge de
balayage mesurée (−2,97 mm) est bien pire que celle des poses (−0,26 mm).

La subdivision se fait sur une **borne prouvée** du déplacement
(`|Δp| ≤ |Δtcp| + reach·Δangle`), pas sur un nombre d'échantillons arbitraire :
une translation de 10 mm demande 20 poses, une rotation de 30° en demande 129.

## Sécurité — non négociable

**L'IA ne pilote jamais les moteurs.** Toute trajectoire doit traverser :

```
collision_engine → kinematics_solver → simulation_engine → safety_state_machine
                                                                    ↓ approbation
                                                          postprocessor_linuxcnc
                                                                    ↓
                                                    linuxcnc_gateway → LinuxCNC
```

- Toute approbation est liée au **hash du Setup**. Déplacer un mors, remesurer
  un outil ou corriger l'origine pièce **invalide l'approbation** — vérifié par
  test, pas seulement documenté.
- **Seul** `linuxcnc_gateway` peut ouvrir un transport machine. Un test parcourt
  le source pour le garantir.
- **LinuxCNC est la seule couche autorisée à produire du mouvement réel.**
- **E-stop et interlocks critiques sont matériels et indépendants** du logiciel.
- `vision_service` produit des **observations**, jamais des commandes.

## Précision

**±0,02 mm n'est pas une caractéristique de ce logiciel.** C'est un objectif de
qualification physique, à démontrer sur pièce d'épreuve usinée **puis mesurée**,
machine par machine. Un kit assemblé par l'acheteur a une chaîne mécanique que
le logiciel ne peut pas garantir. `CalibrationReport.precision_statement()`
renvoie « Précision NON QUALIFIÉE » tant que la mesure n'a pas eu lieu.

## Pile technique

Python 3.11+ · **OCCT 8.0.1** via `cadquery-ocp` (wheels x86_64 **et aarch64**,
donc `pip install` sur Raspberry Pi 5) · NumPy/SciPy · pydantic · matplotlib
(rendu hors-ligne).

Performance mesurée (x86_64) : **51 ms/point** d'accessibilité avec le garde
machine actif, contre 199 ms avant l'inversion de son transport. La résolution
adaptative donne ×1,8 à ×4,3 selon la contrainte géométrique, en rendant le même
verdict de faisabilité que le calcul complet. **Jamais mesuré sur Pi 5** :
l'extrapolation ×3–5 reste une extrapolation.

Aucune dépendance AGPL dans le paquet distribué — voir
[l'audit](docs/audit/dependencies-licenses.md).

## Licence

**Volontairement non décidée** (ADR-001 / D10, à trancher en ADR-002). C'est une
décision commerciale — kit vendu, LinuxCNC GPLv2 en aval, distribution de
l'image Pi — qui dépasse le cadre technique. Poser une licence par inadvertance
coûterait plus cher que de ne pas en poser.
