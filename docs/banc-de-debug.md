# Banc de debug visuel — V1

Outil de contrôle pour le porteur du projet : **voir** ce que le moteur calcule
au lieu d'en lire les journaux. Ce n'est pas l'IHM destinée au client.

## Installation pas à pas

Prérequis : **Python 3.11 ou plus**, et **git**. Sur Windows, remplacer
`python3` par `python` dans toutes les commandes.

```bash
# 1. Récupérer le code
git clone https://github.com/valorcia/logiciel-cnc
cd logiciel-cnc
git checkout claude/amazing-lovelace-a85fl3

# 2. Créer un environnement isolé (évite de polluer le Python du système)
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate

# 3. Installer
pip install -e ".[ui,viz,dev]"
```

Le corpus de 20 pièces STEP est **déjà dans le dépôt** : rien à générer.

### Vérification en trois marches

Monter dans cet ordre. Si une marche échoue, la suivante ne dira rien d'utile.

**Marche 1 — le moteur seul** (aucune image, aucune fenêtre) :

```bash
python3 -m pytest -q
```

Attendu : `290 passed`. Si des tests d'image sont sautés (`skipped`), c'est
normal sur une machine sans rendu 3D — voir la section « Rendu sans écran ».

**Marche 2 — une image, sans fenêtre** :

```bash
python3 -m xyzac.ui.debug --step tests/corpus/step/C10_dome_convexe.step \
    --capture out/essai.png
```

Attendu : les cotes de la pièce s'affichent, puis `capture : .../out/essai.png`.
Ouvrir l'image : on doit voir le dôme ambre, le brut transparent et l'outil
complet. **Si cette marche passe, le moteur et le rendu fonctionnent** — ce qui
reste n'est plus qu'une question d'affichage.

**Marche 3 — la fenêtre** :

```bash
python3 -m xyzac.ui.debug --step tests/corpus/step/C10_dome_convexe.step
```

### Ce qu'il faut essayer dans la fenêtre

| Geste | Attendu |
|---|---|
| Glisser avec le bouton gauche | la scène tourne |
| Molette | zoom |
| Décocher « Brut » à gauche | la boîte transparente disparaît |
| Décocher « Porte-outil » | l'écrou et le nez de broche disparaissent, la fraise reste |
| Onglet « Axes » à droite | X, Y, Z, A, C, et la mention « pose d'inspection » |
| `IMPORTER STEP` | choisir un autre fichier de `tests/corpus/step/` |
| `Voir tout` | recule jusqu'aux limites de course |
| `CAPTURE DEBUG` | le chemin de l'image s'écrit en bas de la fenêtre |
| Fermer la fenêtre | le programme rend la main, sans processus restant |

Pièces intéressantes à charger : `C01_bloc_simple` (le plus simple),
`C02_poche_droite`, `C06_contre_depouille`, `C10_dome_convexe`,
`C13_arbre_gorge_torique`.

### Si quelque chose ne marche pas

Envoyez-moi **la commande lancée et le message d'erreur complet**, plus le
résultat de :

```bash
python3 -c "import sys, platform; print(sys.version, platform.platform())"
python3 -c "import PySide6, pyvista, vtk; print('ui ok')"
```

Sur Linux, une fenêtre qui refuse de s'ouvrir demande souvent des
bibliothèques système absentes :

```bash
sudo apt-get install -y libegl1 libxkbcommon-x11-0 libdbus-1-3 libfontconfig1
```

L'extra `ui` est **optionnel** : le moteur s'installe et tourne sans lui, et un
test le vérifie (`test_no_compute_module_depends_on_the_ui_stack`). C'est ce qui
permet de faire tourner les calculs sur une machine sans écran.

## Lancement

```bash
# Fenêtre interactive (machine avec écran)
python -m xyzac.ui.debug

# Avec une pièce ouverte d'emblée
python -m xyzac.ui.debug --step tests/corpus/step/C10_dome_convexe.step

# Capture sans écran (SSH, Raspberry Pi, intégration continue)
python -m xyzac.ui.debug --step piece.step --capture out/vue.png

# Capture en masquant des calques, avec rotation et zoom
python -m xyzac.ui.debug --step piece.step --capture out/vue.png \
    --hide stock,limits,machine --azimuth 40 --zoom 1.5
```

Sans écran, la fenêtre **refuse de s'ouvrir et dit pourquoi** plutôt que de
planter dans VTK.

## Ce que la V0 fait

| | |
|---|---|
| Importer un STEP | par l'importeur **contrôlé** du moteur (`load_step_checked`), donc avec son diagnostic et son refus d'une forme inutilisable |
| Voir la pièce | maillage du tesselateur du moteur, identifiants de face conservés |
| Voir le brut | dérivé automatiquement autour de la pièce |
| Voir l'outil **complet** | arête, goujure, col, tige, porte-outil, nez de broche — un calque par groupe, couleur par rôle |
| Voir les axes A et C | droites et pivots à leur position déclarée |
| Voir les courses | boîte filaire des limites linéaires |
| Tourner, zoomer | à la souris dans la fenêtre ; par programme via `--azimuth` / `--zoom` |
| Afficher/cacher | arborescence de calques à cases à cocher |
| Panneau X/Y/Z/A/C | valeurs réelles d'une **pose d'inspection**, transport par le `KinematicsSolver` |
| Capture | bouton `CAPTURE DEBUG`, ou `--capture` |

## V1 — accessibilité et orientations 5 axes

C'est le différenciateur du projet rendu manipulable. Toutes les données
existaient déjà dans `AccessibilityMap` ; la V1 les affiche.

```bash
# Lister les faces d'une pièce
python -m xyzac.ui.debug --step tests/corpus/step/C04_rainure_profonde.step --faces

# Analyser une face, placer l'outil à la meilleure orientation, capturer
python -m xyzac.ui.debug --step tests/corpus/step/C04_rainure_profonde.step \
    --analyse-face 1 --points 8 --capture out/orient.png
```

Dans la fenêtre : onglet **Accessibilité** à droite → choisir une face, un
outil, un nombre de points, puis `ANALYSER L'ACCESSIBILITÉ`. La liste des
orientations s'affiche, admissibles d'abord ; **cliquer une ligne place l'outil
à cette orientation** dans la vue 3D.

### Les flèches

Un éventail part du point de contact, une couleur par famille de rejet, un
calque par famille — pour pouvoir demander « montre-moi seulement ce que le
porte-outil interdit ».

| couleur | famille |
|---|---|
| vert | admissible |
| rouges, du clair au sombre | collision d'un tronçon : arête → col → tige → porte-outil → nez de broche |
| rouge très sombre | collision d'un organe machine |
| orange | hors course A/C ou X/Y/Z |
| violet | singularité |
| gris | écarté par le filtre géométrique, avant tout calcul physique |

### Deux réglages par défaut qui changent tout, et pourquoi

**Outil hémisphérique par défaut.** Sur la face supérieure du bloc C01, une
fraise à bout **droit** a 2 orientations admissibles, une hémisphérique en a
**106** — un facteur 53. Ce n'est pas un défaut du moteur mais une physique
connue depuis M1 : sur une face plane une fraise à bout droit ne peut ni
travailler verticale (singularité) ni inclinée (son talon enfonce la matière).
Le banc ouvrait sur cet outil et faisait donc conclure que tout était
inaccessible.

**Singularité A = 0 permise par défaut.** Elle est un problème de *mouvement*,
pas de position (ADR-003) : en indexation 3+2 l'axe C est bloqué et A = 0 est
parfaitement utilisable. La rejeter fait déclarer inatteignable une face que
trois axes suffisent à usiner. Effet mesuré : 106 orientations en la rejetant,
118 en la permettant.

Les deux réglages sont **affichés dans le panneau**, avec la jauge, le lead
maximal, la finesse de grille, la hauteur de cales — et la mention que
**l'absence de bridage rend le résultat optimiste**. Un nombre d'orientations
admissibles ne veut rien dire sans ses hypothèses.

### Le panneau Collision

Tronçon par classe d'obstacle : arête, col, tige, porte-outil, nez de broche
contre pièce, brut, bridage, et l'outil complet contre les organes machine.
Trois choses qu'il ne fait pas, et chacune corrige un défaut de sa première
version :

- **pas de marge par ligne.** `min_margin` est un minimum global : le reporter
  par ligne attribuait à la tige un nombre appartenant à l'arête, et affichait
  « dégagé, −2,335 mm ». La marge figure une seule fois, avec le tronçon
  auquel elle appartient ;
- **agrégation par rôle**, pas par tronçon : un bec hémisphérique compte huit
  tronçons `cutting` ;
- il interroge le **garde machine**, car les organes machine ne sont pas dans
  le champ d'obstacles — sans quoi la ligne MACHINE annonçait « aucun
  obstacle » alors que c'est la cause de rejet la plus fréquente du corpus.

Et il emploie la **même tolérance d'arête** que le solveur : sans elle il
signalait « arête / PIÈCE : 804 points en violation » sur des orientations
déclarées admissibles. Un panneau de debug qui contredit le moteur est pire
que pas de panneau.

## Architecture

Trois couches, et la séparation a une raison pratique autant que théorique :

```
src/xyzac/ui/debug/
├── palette.py   code couleur unique et partagé            sans Qt
├── state.py     ce qui est chargé, et ce qu'on en dit     sans Qt
├── scene.py     traduction en objets 3D, captures          sans Qt
├── window.py    coquille Qt : arbre, panneaux, boutons     Qt
└── app.py       point d'entrée, détection d'écran
```

`state` et `scene` sont **sans Qt**, donc testables sans écran — c'est là que
vit tout ce qui est vérifié. `window` ne contient que des widgets, précisément
parce que c'est la couche qu'on ne peut pas tester ici.

Aucune couche ne contient d'algorithme métier : tout vient de `geometry_core`,
`machine_model`, `tool_model`, `stock_engine`, `kinematics_solver`. Deux tests
différentiels l'imposent — le transport pièce → machine du banc doit coïncider
**point par point** avec celui du moteur.

## Code couleur

| couleur | sens |
|---|---|
| vert | orientation ou mouvement valide |
| rouge | collision |
| orange | proche d'une collision ou d'une limite |
| bleu | trajectoire outil |
| gris transparent | brut |
| ambre | pièce finale |

Une seule source (`palette.py`). Vert et rouge se séparent aussi en luminance,
pour rester lisibles en cas de daltonisme rouge-vert.

## Sécurité

**Aucun bouton de ce banc ne peut déplacer une machine.** Aucun module du
paquet n'importe `linuxcnc_gateway` ni le post-processeur, et un test le
vérifie sur l'arbre syntaxique — pas par recherche de texte, qui se trompait de
cible en se déclenchant sur les commentaires.

Le bandeau « SIMULATION » de la fenêtre n'est pas un état : c'est une constante.

## Limites de la V0, à lire avant de signaler un défaut

| Limite | Détail |
|---|---|
| **Rotation à la souris non vérifiée par moi** | le conteneur de développement n'a pas d'écran. Elle est assurée par l'interacteur de VTK, qui n'est pas du code de ce projet. `--azimuth` / `--zoom` font la même chose par programme, et sont testés |
| **Rendu dans le widget Qt non vérifié** | la fenêtre se construit, charge un STEP, attache la scène, bascule ses calques et se ferme proprement — tout cela est testé. Que des pixels apparaissent dans le widget ne l'est pas |
| ~~Organes machine justes à A = C = 0~~ | **corrigé en V1** : plateau, berceau et axe C sont animés par (A, C). Un test vérifie que la distance pièce/plateau est invariante à toute pose |
| Pose d'inspection, pas trajectoire | les X/Y/Z/A/C sont ceux d'une pose **choisie**. Le panneau le dit |
| Calques restants | matière restante, bridage, trajectoire : déclarés, désactivés, annoncés « non disponible » |
| Bridage non modélisé | l'analyse d'accessibilité est donc **optimiste**, et le panneau le dit |
| Coût de l'analyse | ~70 ms par point de contact. Une face de mille points prendrait une minute : le nombre de points est un réglage, et le rapport dit toujours combien la face en contient |
| Sélection de face à la souris | pas encore : la face se choisit dans une liste triée par aire. Les `face_id` sont déjà transportés dans le maillage |
| Avances et vitesses | « non disponible » : `recipe_profiles` est une ébauche |
| Une capture reconstruit la scène | ~1 s. Voir `scene.capture` : sur le rendu logiciel sans écran, une fenêtre de rendu ne produit qu'une image et ignore tout changement ultérieur |

## Rendu sans écran

Le mode `--capture` a besoin d'un rendu logiciel. Sur Ubuntu :

```bash
apt-get install -y libosmesa6 libegl1
export VTK_DEFAULT_OPENGL_WINDOW=vtkOSOpenGLRenderWindow
```

Les tests d'image se **sautent** automatiquement si ce rendu est absent ; les
tests d'état, eux, tournent toujours.
