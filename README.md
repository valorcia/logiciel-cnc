# Slicer soustractif XYZAC

Moteur de fabrication soustractive 5 axes pour un centre d'usinage maker
**XYZAC** vendu en kit. L'utilisateur importe un STEP, définit un brut, et la
machine calcule seule comment enlever le volume `brut \ pièce`.

Ce n'est **pas** un CAM généraliste : l'utilisateur ne programme pas
d'opérations. Ce n'est **pas** un portage d'OrcaSlicer : l'inspiration est
l'expérience utilisateur des slicers 3D, le moteur est propre et soustractif.

> **État : jalon M11.** Ébauche indexée, finition à crête contrôlée — le pas
> venant de la **courbure locale mesurée** — et tournage sur l'axe C. La gouge
> du porte-outil est **prouvée sur toute la passe**, et non sondée. La machine
> se **mesure** : localisation des axes A et C au palpeur, erreurs compensées,
> incertitude budgétée. Les avances viennent de recettes sourcées et
> déclassées ; approche et dégagement sont portés par la trajectoire et
> validés au balayage. La **configuration LinuxCNC** (`xyzac-trt-kins`) est
> désormais dérivée du modèle et du dossier de calibration, et le programme est
> **déposé dans un fichier** derrière quatre conditions ordonnées.
>
> La configuration a été **chargée par LinuxCNC 2.9**, compilé depuis sa source
> en mode `uspace` : elle démarre, la cinématique est instanciée, les cinq
> articulations existent. Cette épreuve a révélé **cinq défauts**, dont deux
> silencieux — voir [la note de validation](docs/validation-linuxcnc.md).
>
> Quand une seule pose ne suffit pas, le moteur **ordonnance les montages** :
> six candidats — et non vingt-quatre, l'axe C continu rendant identiques les
> poses qui ne diffèrent que par une rotation en Z. Pour chaque face non
> couverte il sépare ce qui tient au **montage** de ce qui tient à l'**outil**,
> en éprouvant le point sur une **machine idéale**. Sur le dôme, quatre passes
> que M10 déclarait rejetées sont en réalité atteignables à 75–88 %, le résidu
> se comptant en un ou deux points.
>
> La finition est désormais décidée sur la **passe complète** et non sur un
> préfixe : le mode annoncé n'est plus celui d'un échantillon. La gamme du dôme
> C10 (159 899 points) est tranchée en **208 s**, contre 1 091 s pour 18 % de
> couverture auparavant — quatre passes prouvées 3+2 **en chacun de leurs
> points**, quatre rejetées définitivement avec leur motif et leur remède.
>
> Les deux cinématiques ont été **recoupées chiffre par chiffre**, jusqu'au
> bout : `part_to_machine_point` et `xyzacKinematicsInverse` s'accordent à
> **7,1·10⁻¹⁵ mm** contre la fonction compilée, et à **1,4·10⁻¹⁴ mm** sur
> **LinuxCNC en marche** — 56 poses commandées en MDI, articulations relues.
> La correspondance de broches d'avant correction donnait **10,286 mm**.
>
> Ce qui n'est **pas** acquis : les **bridages** (le banc n'en connaît pas, donc
> toute couverture est optimiste) et le **transfert d'origine** entre montages —
> chaque remontage reréférence la pièce, les budgets se composent, et le moteur
> refuse d'annoncer une tolérance d'un montage à l'autre. La **trajectoire
> simultanée** sur une passe
> complète, qui demande le champ admissible en chaque point et reste à trois
> heures. Le **signe** des offsets de pivot, qu'aucun
> calcul n'établit — il faut commander un déplacement et regarder. Le HAL
> produit est de **simulation**. Aucun lancement de cycle n'existe, **par
> décision**. Le dépôt vers une cible matérielle reste refusé tant que la
> pièce d'épreuve n'a pas été usinée **puis mesurée**. Voir
> [ADR-001 §6](docs/adr/ADR-001-architecture-fondatrice.md),
> [ADR-002](docs/adr/ADR-002-jalon-M2.md),
> [ADR-003](docs/adr/ADR-003-jalon-M3.md),
> [ADR-004](docs/adr/ADR-004-jalon-M4.md),
> [ADR-005](docs/adr/ADR-005-jalon-M5.md),
> [ADR-006](docs/adr/ADR-006-jalon-M6.md),
> [ADR-007](docs/adr/ADR-007-jalon-M7.md),
> [ADR-008](docs/adr/ADR-008-jalon-M8.md),
> [ADR-009](docs/adr/ADR-009-jalon-M9.md),
> [ADR-010](docs/adr/ADR-010-jalon-M10.md),
> [ADR-011](docs/adr/ADR-011-jalon-M11.md).

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

**Pour essayer, sans rien connaître du moteur :**

```bash
pip install -e ".[viz]"
python tools/make_corpus.py       # 20 géométries d'exemple
python -m xyzac.ui.atelier        # ouvre l'Atelier dans le navigateur
```

L'Atelier répond à une question : **cette machine peut-elle faire cette
pièce ?** Vous chargez une pièce, vous réglez les cotes que vous n'avez pas
encore coulées dans le métal — courses, bascule A, plateau, outil — et il
répond surface par surface, avec ce qu'il faut faire. Voir
[docs/atelier.md](docs/atelier.md).

---

## Démarrage détaillé

```bash
pip install -e ".[viz,dev]"

python tools/make_corpus.py                  # 20 géométries STEP synthétiques
python tools/make_degraded_corpus.py         # 3 STEP volontairement abîmés
python -m pytest tests/ -q                   # 421 tests

# M1 — accessibilité + orientation + visualisation
python tools/demo_vertical_slice.py C08
python tools/demo_vertical_slice.py C10 --ballnose --face 6   # 5 axes simultané

# M2 — pipeline complet jusqu'aux portes de sécurité
python tools/demo_m2_pipeline.py C02 --face 2 --ballnose --material finished

# M3 — STEP -> GAMME -> validation, sans passe écrite à la main
python tools/demo_m3_pipeline.py C02 --max-setups 1

# M7 — erreur injectée -> calibration -> compensation -> G-code -> envoi refusé
python tools/demo_m7_calibration.py C10 --out /tmp/piece.ngc

# M9 — configuration LinuxCNC dérivée, dépôt simulation accepté / matériel refusé
python tools/demo_m9_linuxcnc.py --out out/config-xyzac

# Performance : référence x86_64, ou comparaison sur la machine cible
python tools/bench_platform.py --json mesure.json
python tools/bench_platform.py --compare docs/bench/x86_64.json

# Recoupement des deux cinématiques (étage 2 : avec un arbre source LinuxCNC)
python tools/verify_kinematics_linuxcnc.py --exagere                     # étage 1
python tools/verify_kinematics_linuxcnc.py --exagere --linuxcnc-source ~/linuxcnc
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
| [ADR-007](docs/adr/ADR-007-jalon-M7.md) | jalon M7 : calibration mesurée, compensation, post-processeur sous scellés |
| [ADR-008](docs/adr/ADR-008-jalon-M8.md) | jalon M8 : recettes de coupe, approche et dégagement, un programme exécutable |
| [ADR-009](docs/adr/ADR-009-jalon-M9.md) | jalon M9 : configuration LinuxCNC dérivée, dépôt de programme, pas de lancement de cycle |
| [ADR-010](docs/adr/ADR-010-jalon-M10.md) | jalon M10 : décider une passe de finition complète — explorer coûte 65 ms, vérifier 1,6 ms |
| [ADR-011](docs/adr/ADR-011-jalon-M11.md) | jalon M11 : ordonnancer les montages, et séparer ce qui tient au montage de ce qui tient à l'outil |
| [Atelier](docs/atelier.md) | l'interface de l'utilisateur : charger, régler, vérifier, simuler |
| [Banc de debug](docs/banc-de-debug.md) | interface de contrôle visuel : ce qu'elle montre, comment la lancer |
| [Performance et Pi 5](docs/bench/README.md) | où passe le temps, la référence x86_64, et la procédure sur Raspberry Pi 5 |
| [Validation LinuxCNC](docs/validation-linuxcnc.md) | compiler LinuxCNC, lui donner la configuration, les sept défauts trouvés, et le recoupement chiffré des deux cinématiques jusqu'à l'exécution |
| [Accessibility Solver](docs/algorithms/accessibility-solver.md) | algorithme, garantie conservative, performance mesurée |
| [Orientation Solver](docs/algorithms/orientation-solver.md) | Viterbi, segmentation 3+2, raffinement |
| [Plan de tests](docs/testplan/plan-de-tests.md) | 20 géométries, 421 tests, ce qui n'est pas testé |

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

## La machine se mesure, et ce qui reste se budgète

Point que les six premiers jalons rendaient facile à oublier : **toutes leurs
marges étaient calculées sur une machine parfaite.** Les jeux valaient 0,0, les
pivots A et C étaient à leur cote nominale. Une marge de 0,7 mm annoncée sur une
poche était une marge géométrique, pas une marge machine.

Une machine non calibrée n'a donc pas une erreur nulle : elle a une incertitude
**inconnue**, et le moteur refuse d'en tirer un budget plutôt que de lire des
zéros.

La localisation des axes se mesure au palpeur, par une sphère de référence
palpée à plusieurs rotations : ses centres décrivent un cercle dont la normale
est la direction de l'axe. Vérifié en **injectant une erreur connue dans le
jumeau** et en exigeant que la procédure la retrouve — 0,20° d'inclinaison
d'axe retrouvés à 0,008° près avec un palpeur à 3 µm.

Une erreur mesurée est ensuite **compensable** : 261 µm et 0,33° d'erreur
injectée cumulée retombent à zéro après compensation. Ce qui ne se compense pas
est l'**incertitude de la mesure**, et elle grandit avec le bras de levier :

| bruit de palpage | budget géométrique à 100 mm des pivots |
|---|---|
| 1 µm | 30 µm |
| 3 µm | 74 µm |
| 10 µm | 229 µm |

Ce tableau est l'un des résultats les plus utiles du projet : il dit
qu'un kit calibré avec un palpeur ordinaire a un budget géométrique de
plusieurs dizaines de microns, **hors effets thermiques, flexion et
hystérésis**. Il contredit donc ±0,02 mm, et c'est précisément son utilité.

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
  l'AST de tout le paquet pour le garantir — et au jalon M9 la passerelle ne
  s'en sert toujours pas : elle **écrit des fichiers**.
- **LinuxCNC est la seule couche autorisée à produire du mouvement réel.**
- **Aucun lancement de cycle n'existe**, et c'est une décision, pas un manque :
  `linuxcnc_gateway.start_cycle` lève, et un test le maintient. Ce qui traverse
  la frontière est un fichier, que l'opérateur charge lui-même.
- Le dépôt vers une cible **matérielle** exige en plus une machine **qualifiée**
  (pièce d'épreuve usinée puis mesurée). La simulation reste ouverte : l'exiger
  des deux ferait une porte verrouillée sur sa propre clé.
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

Performance mesurée (x86_64, Xeon 2,8 GHz) : **explorer** l'ensemble
admissible en un point coûte **75 ms**, **vérifier** une orientation déjà
connue **1,5 ms** — c'est ce rapport de 50 qui rend décidable une passe de
finition complète (M10). Pic mémoire de la décision complète : **789 Mo**,
donc un Pi 5 de 4 Go suffit.

**Toujours pas mesuré sur Pi 5** — l'environnement de développement est
x86_64 et une mesure sous émulation ne vaudrait rien. Mais la mesure est
désormais *franchissable* plutôt que repoussée : `tools/bench_platform.py`
produit les mêmes chiffres sur les deux machines, la référence x86_64 est
enregistrée, et la roue `cadquery-ocp` aarch64 est vérifiée. Voir
[docs/bench](docs/bench/README.md).

Aucune dépendance AGPL dans le paquet distribué — voir
[l'audit](docs/audit/dependencies-licenses.md).

## Licence

**Volontairement non décidée** (ADR-001 / D10, à trancher en ADR-002). C'est une
décision commerciale — kit vendu, LinuxCNC GPLv2 en aval, distribution de
l'image Pi — qui dépasse le cadre technique. Poser une licence par inadvertance
coûterait plus cher que de ne pas en poser.
