# ADR-001 — Architecture fondatrice du slicer soustractif XYZAC

- **Statut** : Accepté (jalon M0)
- **Date** : 2026-09-11
- **Décideurs** : Lead Architect / Senior CAM-Geometry
- **Remplace** : —
- **Portée** : choix de noyau géométrique, de découpage modulaire, de cinématique, de
  frontière de sécurité et de politique de licences pour le produit « slicer soustractif XYZAC ».

---

## 1. Contexte

Nous construisons un **slicer soustractif** : l'utilisateur importe un STEP, définit un brut,
et la machine calcule seule comment enlever le volume `brut \ pièce`. Ce n'est **pas** un CAM
généraliste (pas de programmation d'opérations par l'utilisateur), et ce n'est **pas** un portage
d'OrcaSlicer (dont le moteur est additif, planaire, et sans modèle de collision d'outil).

La machine cible est un centre **XYZAC** vendu en kit :
- 3 axes linéaires X, Y, Z ;
- un axe rotatif **A** (berceau, rotation autour de X) ;
- un axe rotatif **C** (plateau, monté sur le berceau A, rotation autour de Z local) ;
- broche à axe **fixe** dans le repère machine (pas de tête orientable) ;
- donc une cinématique **table/table** : c'est la **pièce** qui s'oriente, pas l'outil.

Le différenciateur produit est explicite : **calculer l'orientation 5 axes en modélisant l'outil
complet** (arête de coupe, goujure, col, tige, porte-outil, nez de broche) et pas seulement le
point TCP, puis produire une **séquence A/C continue, rigide et éloignée des singularités**.

Ajout structurant : **C doit pouvoir être un axe d'indexation ET un axe de tournage continu**.
L'architecture doit donc porter deux cinématiques de coupe (fraisage / tournage) sans les mélanger
implicitement.

---

## 2. Problème à décider maintenant

1. Quel noyau B-Rep, et sous quelle forme de distribution (le produit doit tourner sur Raspberry Pi 5) ?
2. Réutilise-t-on FreeCAD CAM/Path et OpenCAMLib comme moteurs, comme adapters, ou pas du tout ?
3. Quelle représentation géométrique pour les tests de collision outil complet / pièce / brut / bridage ?
4. Comment structurer la frontière entre calcul (Python/IA) et mouvement réel (LinuxCNC) ?
5. Quelle politique de licence, sachant que le logiciel est distribué avec un kit commercial ?

---

## 3. Décisions

### D1 — Noyau géométrique : OCCT, via les bindings **OCP** (`cadquery-ocp`), pas `pythonocc-core`

**Décision** : `geometry_core` s'appuie sur **Open CASCADE Technology 8.0.1** exposé par le paquet
PyPI `cadquery-ocp` (bindings pybind11 « OCP »).

**Justification mesurée sur cet environnement** (pas depuis la mémoire) :

| Critère | `pythonocc-core` | `cadquery-ocp` (OCP) |
|---|---|---|
| Disponible sur PyPI | **Non** (`No matching distribution found`) | **Oui**, 8.0.1.0.0 |
| Wheel `manylinux_2_28_x86_64` | — | **Oui** (66,9 Mo) |
| Wheel `manylinux_2_28_aarch64` (Pi 5) | — | **Oui** (61,6 Mo) |
| Installation vérifiée ici | — | **Oui**, `STEPControl_Reader` importé |

La disponibilité d'un wheel **aarch64** est décisive : la cible embarquée est un Raspberry Pi 5.
Avec `pythonocc-core` nous imposerions conda/miniforge ou une compilation OCCT sur Pi (plusieurs
heures, et un casse-tête de support pour un produit en kit). Avec OCP, `pip install` suffit sur les
deux architectures, ce qui aligne poste de travail et machine.

**Conséquence** : l'API OCCT utilisée est l'API C++ transposée (`OCP.*`), pas l'API `OCC.Core.*`.
`geometry_core` encapsule cette différence derrière une façade maison afin qu'un futur basculement
vers `pythonocc-core` reste une réécriture d'adapter et non du code métier.

### D2 — Représentation duale B-Rep / discret, avec une **garantie conservative explicite**

**Décision** : deux représentations coexistent et ne servent pas au même usage.

- **B-Rep exact (OCCT)** : import/export STEP, topologie, faces, normales analytiques, booléens de
  brut, détection de révolution, mesure. C'est la **vérité géométrique**.
- **Échantillonnage discret conservatif** : nuage de points orienté (issu d'une tessellation
  contrôlée par tolérance de flèche `δ`) pour toutes les requêtes de **proximité et de collision**
  à haute cadence.

**Règle de sûreté associée, non négociable** : tout obstacle échantillonné avec un pas maximal `δ`
est **inflaté de `δ`** avant test. Le test discret devient alors un **majorant** de la collision
réelle : il peut refuser une orientation géométriquement admissible (faux négatif de faisabilité),
il ne peut pas accepter une orientation en collision. Le solveur est donc **conservatif par
construction**, ce qui est la seule posture acceptable pour piloter une broche.

**Rejeté** : voxelisation pure (mémoire O(n³) sur Pi 5, et perte de la normale analytique dont
l'orientation solver a besoin). Le voxel reste envisagé **uniquement** dans `stock_engine` pour le
suivi de matière restante (« dexel/voxel de brut »), où l'exactitude B-Rep coûte trop cher.

### D3 — FreeCAD CAM/Path et OpenCAMLib : **adapters optionnels, jamais le moteur**

**Audit** (détail dans `docs/audit/`) :
- **OpenCAMLib** — LGPL 2.1 depuis 2018, disponible sur PyPI. Algorithmes solides et éprouvés
  (drop-cutter, waterline) mais **intrinsèquement 3 axes** : `drop cutter` descend un outil selon
  une direction fixe. Aucune notion de porte-outil, de nez de broche, ni d'orientation.
- **FreeCAD CAM (ex-Path)** — LGPL 2+. Moteur CAM classique **piloté par opérations** : l'utilisateur
  choisit poche/contour/surfaçage. C'est exactement le modèle mental que notre produit refuse.
  Réutilisable en bibliothèque via `ocp-freecad-cam`, mais impose FreeCAD entier comme dépendance.

**Décision** : ni l'un ni l'autre n'est le moteur. `strategy_planner` définit une interface
`ToolpathBackend` ; OCL devient un backend pour les passes **3 axes / 3+2 dans un plan indexé**
(là où il est excellent et où nous n'avons rien à réinventer), et FreeCAD CAM reste un backend de
**comparaison/validation** hors ligne, non embarqué.

**Raison de fond** : notre valeur est en amont de ces bibliothèques (accessibilité, orientation,
séquencement A/C). Si nous partions de leur modèle de données, nous hériterions d'un monde où
l'outil est un rayon et une longueur, sans porte-outil — précisément ce que nous voulons résoudre.

### D4 — L'**outil est un solide de révolution étagé**, jamais un rayon

**Décision** : `tool_model.ToolAssembly` est une **pile de tronçons coaxiaux** (cylindres et cônes
tronqués), du bout de l'outil jusqu'au nez de broche, chacun portant son propre rôle :
`CUTTING`, `NECK`, `SHANK`, `HOLDER`, `SPINDLE_NOSE`.

Cette forme a une propriété exploitée partout : dans le repère outil (axe = +z), l'appartenance
d'un point `(r, z)` au solide se teste par `r < R(z)` avec `R` linéaire par morceaux. Le test de
collision devient donc une opération **vectorisable NumPy en O(N_points)** par orientation, sans
BVH ni maillage. C'est ce qui rend l'exploration de centaines d'orientations par point de contact
tenable sur un Pi 5.

**Conséquence majeure** : une collision n'est pas un booléen mais **une collision avec un tronçon
identifié**. Un contact `CUTTING` en dessous de la profondeur de passe est une gouge ; un contact
`HOLDER` est un défaut d'accessibilité qui se corrige par allongement d'outil ou par basculement.
Le solveur peut donc **expliquer un rejet**, et l'UI peut dire « le porte-outil touche, essaie une
tige de 45 mm » plutôt que « échec ».

### D5 — Cinématique XYZAC table/table posée **explicitement**, et assumée non triviale

Repères : pièce → plateau C → berceau A → machine. Broche fixe selon `+Z` machine.

`R_machine←pièce = Rx(A) · Rz(C)`

Direction d'axe outil exprimée dans le repère pièce (pointant du bec vers la broche) :

```
d_pièce(A, C) = ( sin A · sin C ,  sin A · cos C ,  cos A )
```

Cinématique inverse :

```
A = ± arccos(d_z)          (deux branches)
C = atan2(d_x, d_y)        (branche A > 0 ; branche A < 0 ⇒ C + π)
```

**Deux conséquences architecturales tirées de cette formule :**

1. **Singularité en A → 0** : quand l'axe outil est aligné sur Z pièce, `C` est indéterminé. Un
   déplacement infinitésimal de l'axe outil peut exiger une rotation `C` de 180°. Le coût de
   singularité n'est donc pas cosmétique : c'est une contrainte de faisabilité dynamique.
   `orientation_solver` porte un terme de pénalité `1/sin A` **et** une contrainte dure `|A| ≥ A_min`.
2. **Double solution** : chaque direction admet deux couples (A, C). Le choix ne peut pas se faire
   localement point par point — il dépend des butées, de la continuité avec le point précédent et
   de la rigidité. C'est ce qui **impose un solveur de séquence** (programmation dynamique) plutôt
   qu'une IK point par point. Cette conclusion est le cœur de D6.

### D6 — Le choix d'orientation est un **problème de séquence**, résolu par DP + raffinement continu

**Décision** : `orientation_solver` procède en deux temps :
1. **Viterbi (programmation dynamique)** sur les orientations candidates discrétisées par point,
   avec coût de transition (continuité A/C, course rotative, faisabilité de l'interpolation) ;
2. **raffinement continu local** sous contrainte, initialisé par la solution DP.

**Rejeté** : IK gloutonne point par point (produit des retournements C de 180° au milieu d'une
passe), et optimisation globale non convexe sans initialisation (ne converge pas de façon fiable,
et surtout n'est pas *reproductible* — inacceptable pour une machine).

La DP donne une propriété que nous voulons pouvoir défendre : **optimalité sur l'ensemble
discrétisé**, et déterminisme. Deux exécutions sur le même STEP donnent le même G-code.

### D7 — **3+2 par défaut, simultané par exception**, décidé par intersection d'ensembles admissibles

**Décision** : après calcul des ensembles admissibles `F_i ⊂ S²` par point, on balaie la trajectoire
en maintenant l'**intersection courante** `⋂ F_i`. Tant qu'elle est non vide, les points partagent
une orientation fixe → **segment 3+2 indexé**. Quand elle se vide, on ferme le segment et on ouvre
le suivant. Le **simultané n'apparaît que là où aucune orientation unique n'existe**.

C'est une règle *dérivée de la géométrie*, pas un réglage utilisateur. Elle réalise littéralement
« 3+2 lorsque possible, simultané uniquement lorsqu'utile », et elle est auditable : on peut
afficher pourquoi un segment a basculé en simultané (l'intersection s'est vidée à tel point).

### D8 — Fraisage et tournage : **deux cinématiques, une architecture, aucune fusion implicite**

**Décision** : `turning_engine` est un module de premier rang, pas une option du fraisage.
`machine_model` porte un `CAxisMode ∈ {INDEXED, CONTINUOUS_SPINDLE}` et un **verrou** :
le passage d'un mode à l'autre est une **transition d'état explicite** dans `safety_state_machine`,
qui invalide l'approbation en cours et exige une nouvelle simulation.

Motif : en mode tournage, C tourne à des centaines de tr/min avec la pièce en rotation ; les
hypothèses du collision engine (obstacles quasi statiques dans le repère pièce) **ne tiennent plus**.
Un plan hybride est une **séquence de gammes**, chacune validée dans sa propre cinématique, avec un
point de synchronisation matériel entre les deux. Mélanger les deux dans un même bloc de trajectoire
est interdit par construction.

À ce jalon, `turning_engine` fournit la **détection des régions de révolution** (via `feature_engine`
sur les `Geom_SurfaceOfRevolution` / cylindres / cônes coaxiaux) et l'interface du planner ; il ne
génère aucune trajectoire de tournage.

### D9 — Frontière de sécurité : **l'IA ne franchit jamais la ligne de mouvement**

**Décision** : une trajectoire ne devient exécutable qu'après avoir traversé, dans cet ordre, quatre
portes qui produisent chacune un **artefact signé** :

```
strategy_planner → collision_engine → kinematics_solver → simulation_engine → safety_state_machine
                                                                                      │
                                                            (approbation, hash du setup) ▼
                                                                       postprocessor_linuxcnc
                                                                                      ▼
                                                                          linuxcnc_gateway → LinuxCNC
```

Règles dures :
- `vision_service` (OpenCV/YOLO) **produit des observations, jamais des commandes**. Sa sortie entre
  dans `probing_service`/`assembly_calibration` comme *mesure à valider*, pas comme consigne.
- Toute approbation est liée au **hash du `Setup`** (pièce, brut, bridages, outils, offsets). Une
  modification de setup **invalide** l'approbation. Aucun chemin ne permet de rejouer un G-code
  approuvé sous un autre setup.
- **E-stop et interlocks sont matériels et indépendants** du logiciel. Le logiciel ne peut ni les
  masquer, ni les réarmer, ni en dépendre pour sa propre sûreté.
- `linuxcnc_gateway` est la **seule** frontière d'exécution, et **LinuxCNC la seule couche autorisée
  à produire du mouvement réel**. Rien d'autre dans le dépôt n'ouvre un port machine.

### D10 — Licences : **frontière de processus** autour de l'AGPL, décision de licence produit ouverte

Constats vérifiés (détail et sources dans `docs/audit/dependencies-licenses.md`) :
- **CurviSlicer est AGPL-3.0** et **3 axes**. Donc : référence conceptuelle, **pas** de réutilisation
  de code, ni liaison, ni dérivation.
- **OrcaSlicer / PrusaSlicer sont AGPL-3.0**. Idem : étude UX uniquement.
- **Ultralytics YOLO est AGPL-3.0**, et l'éditeur affirme qu'un usage commercial, même en R&D
  interne, requiert une licence Enterprise. **Risque produit direct** pour un kit vendu.
- OCCT est **LGPL-2.1 + exception Open CASCADE** ; le wheel `cadquery-ocp` déclare Apache-2.0 pour
  le code de binding mais **embarque les binaires OCCT** qui restent sous leur licence propre.

**Décision** : `vision_service` définit une interface `Detector` et le backend par défaut **n'est
pas** Ultralytics. Un backend Ultralytics peut exister mais **hors du paquet distribué**, en plugin
séparé, chargé par l'utilisateur final. Le backend livré vise ONNX Runtime + un modèle sous licence
permissive (Apache-2.0 / MIT).

**Non décidé, à trancher en ADR-002** : la licence du produit lui-même. C'est une décision
commerciale (kit vendu, LinuxCNC GPLv2 en aval, distribution de l'image Pi) qui dépasse le cadre
technique et ne doit pas être tranchée par défaut. **Aucun fichier `LICENSE` n'est donc committé à
ce jalon** — poser une licence par inadvertance est plus coûteux que de ne pas en poser.

### D11 — Python-first, C/C++ **derrière bindings et seulement sur preuve de besoin**

Le chemin chaud est le test outil/obstacle dans l'accessibility solver. Il est aujourd'hui écrit en
NumPy vectorisé. **Règle** : aucune réécriture C/C++ sans profil mesuré sur le matériel cible (Pi 5)
démontrant que le NumPy est le goulot, et sans que l'implémentation native soit couverte par les
mêmes tests que la version Python (test différentiel obligatoire).

---

## 4. Conséquences

**Positives**
- Un seul `pip install` sur poste de travail et sur Pi 5 (wheels x86_64 + aarch64 vérifiés).
- Le rejet d'orientation est *explicable* (quel tronçon d'outil, quel obstacle).
- 3+2 vs simultané est *dérivé*, donc défendable et reproductible.
- Aucune dépendance AGPL dans le produit distribué.

**Négatives / dettes assumées**
- La façade `geometry_core` au-dessus d'OCP est un coût de maintenance permanent.
- L'approche conservative **rejettera des orientations réellement admissibles**. La finesse `δ`
  devient un paramètre de qualité à calibrer, avec un compromis coût/permissivité.
- La DP impose une discrétisation : l'optimum continu n'est atteint qu'au raffinement.
- Ne pas réutiliser FreeCAD CAM signifie réécrire des stratégies éprouvées (poches, contours).

**Risques ouverts (suivis)**
- R1 — Performance du solveur sur Pi 5 : non mesurée. Jalon M2.
- R2 — Robustesse import STEP (tolérances, faces dégénérées, shells non cousus) : jalon M1 via corpus.
- R3 — Précision : **±0,02 mm n'est pas un acquis**. C'est un **objectif de qualification physique**,
  à démontrer sur pièce d'épreuve, après calibration d'assemblage, sur machine réelle. Aucune
  documentation ni UI ne doit l'annoncer comme une caractéristique tant que la pièce de qualification
  n'a pas été mesurée. Le logiciel ne peut garantir que sa **propre** erreur numérique, pas la chaîne
  mécanique d'un kit assemblé par l'acheteur.
- R4 — Licence produit non tranchée (ADR-002) ; bloque la distribution, pas le développement.

---

## 5. Alternatives écartées

| Alternative | Motif de rejet |
|---|---|
| Forker OrcaSlicer | AGPL-3.0 ; moteur additif planaire ; aucun modèle outil/porte-outil ; le refactor dépasserait une réécriture |
| Bâtir sur FreeCAD CAM | Modèle « opérations » contraire au produit ; dépendance lourde ; toujours pas de solveur d'orientation |
| Réutiliser CurviSlicer | AGPL-3.0 ; 3 axes ; additif ; dépend de TetWild et d'un solveur QP — hors sujet soustractif |
| Trimesh/maillage seul comme noyau | Perte de la normale analytique et de la topologie STEP ; l'usinage a besoin de faces, pas de triangles |
| IK gloutonne point par point | Retournements C de 180° ; non déterministe en pratique |
| Voxelisation globale | Mémoire prohibitive sur Pi 5 ; perte des normales |

---

## 6. Ce que ce jalon **n'autorise pas**

- Aucune génération de G-code destinée à une machine réelle.
- Aucune connexion `linuxcnc_gateway` vers un contrôleur.
- Aucune affirmation de précision chiffrée en documentation utilisateur.

Ces trois interdits tombent seulement quand `collision_engine`, `kinematics_solver`,
`simulation_engine` et `safety_state_machine` sont implémentés **et** couverts par des tests.
