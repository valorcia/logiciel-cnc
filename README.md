# Slicer soustractif XYZAC

Moteur de fabrication soustractive 5 axes pour un centre d'usinage maker
**XYZAC** vendu en kit. L'utilisateur importe un STEP, définit un brut, et la
machine calcule seule comment enlever le volume `brut \ pièce`.

Ce n'est **pas** un CAM généraliste : l'utilisateur ne programme pas
d'opérations. Ce n'est **pas** un portage d'OrcaSlicer : l'inspiration est
l'expérience utilisateur des slicers 3D, le moteur est propre et soustractif.

> **État : jalon M1 (prototype R&D).** Aucun G-code n'est généré, aucune
> connexion machine n'est possible. Voir [ADR-001 §6](docs/adr/ADR-001-architecture-fondatrice.md).

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
python tools/demo_vertical_slice.py C08      # STEP → accessibilité → orientation → PNG
python tools/demo_vertical_slice.py C10 --ballnose --face 6   # cas 5 axes simultané
python -m pytest tests/ -q                   # 108 tests
```

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
| [Accessibility Solver](docs/algorithms/accessibility-solver.md) | algorithme, garantie conservative, performance mesurée |
| [Orientation Solver](docs/algorithms/orientation-solver.md) | Viterbi, segmentation 3+2, raffinement |
| [Plan de tests](docs/testplan/plan-de-tests.md) | 20 géométries, 108 tests, ce qui n'est pas testé |

---

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

Aucune dépendance AGPL dans le paquet distribué — voir
[l'audit](docs/audit/dependencies-licenses.md).

## Licence

**Volontairement non décidée** (ADR-001 / D10, à trancher en ADR-002). C'est une
décision commerciale — kit vendu, LinuxCNC GPLv2 en aval, distribution de
l'image Pi — qui dépasse le cadre technique. Poser une licence par inadvertance
coûterait plus cher que de ne pas en poser.
