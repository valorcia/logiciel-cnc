# Accessibility Solver — algorithme détaillé

**Question posée.** En un point de contact `p` de normale `n`, quel est l'ensemble
des directions d'axe outil `d` telles que **l'outil complet** — bec, arête,
col, tige, porte-outil, nez de broche — dégage la pièce, le brut et les
bridages, tout en étant réalisable par la cinématique XYZAC ?

**Sortie.** Pas un booléen par direction, mais un champ : admissible / rejeté,
**pourquoi** rejeté, et **avec quelle marge** si admissible. La marge est ce qui
permet à l'orientation solver d'*optimiser* au lieu de simplement *choisir*.

Convention : `d` pointe **du bec vers la broche**, donc vers l'extérieur de la
matière.

---

## Pipeline

Six étages, du moins cher au plus cher. Chaque étage ne traite que ce que le
précédent n'a pas tranché.

```
E0  génération des candidats      642 directions (icosphère niveau 3, ~8,6°)
E1  filtre géométrique local      face arrière + angle de lead maximal
E2  filtre cinématique            butées A/C, singularité, 2 branches IK
E3  encadrement à deux bornes     (désactivé par défaut — voir §5)
E4  test exact outil complet      par tronçon, vectorisé NumPy
E5  structuration                 composantes connexes → cônes d'accessibilité
```

### E0 — Génération des candidats

Subdivision d'icosaèdre, pas une grille latitude/longitude. Motif : une grille
lat/lon concentre ses points aux pôles, et le pôle est exactement la zone de
singularité `A → 0`. On aurait une résolution absurde là où elle ne sert à rien,
et grossière à l'équateur où elle est critique.

| Niveau | Directions | Écart moyen |
|---|---|---|
| 2 | 162 | 17,2° |
| **3** | **642** | **8,6°** |
| 4 | 2562 | 4,3° |

Le niveau 3 est le défaut. Le raffinement fin est fait **localement** par
l'orientation solver, pas globalement ici.

### E1 — Filtre géométrique local

```
rejet BACK_FACING  si  d·n < min_normal_dot        (l'axe pointe dans la matière)
rejet LEAD_LIMIT   si  d·n < cos(max_lead_deg)     (inclinaison excessive)
```

`max_lead_deg` (45° par défaut) est technologique, pas géométrique : au-delà,
l'état de surface et la charge sur l'outil se dégradent même sans collision.

### E2 — Filtre cinématique

Pour XYZAC table/table, `R_machine←pièce = Rx(A)·Rz(C)`, donc

```
d_pièce(A, C) = (sin A · sin C,  sin A · cos C,  cos A)
A = ± arccos(d_z)
C = atan2(d_x, d_y)      (branche A > 0 ; branche A < 0 ⇒ C + 180°)
```

**Deux branches par direction.** On garde la meilleure branche *réalisable*. Le
choix définitif entre branches revient à l'orientation solver, seul à voir la
séquence — ici on ne fait que constater la réalisabilité. Sur le berceau du kit
(A ∈ [−120°, +30°], dissymétrique), c'est souvent la branche miroir qui passe.

```
rejet AXIS_LIMITS  si aucune branche n'est dans les courses
rejet SINGULARITY  si toutes les branches réalisables ont |A| < singularity_a_deg
```

### E3 — Encadrement à deux bornes (optionnel)

- **Borne supérieure** : un cylindre unique de rayon `max_radius` sur toute la
  longueur *contient* l'outil. S'il dégage, l'outil dégage. Certain.
- **Borne inférieure** : le tronçon de coupe est *contenu* dans l'outil. S'il
  pénètre un obstacle interdit, l'outil pénètre. Certain.

⚠️ **Piège identifié pendant le développement** (et corrigé) : la borne
inférieure n'est valide que sur les couples où le test exact n'accorde **aucune
exemption**. Le couple (coupe, pièce) en accorde deux — `cutting_allowance` et
`cutting_depth`. L'y inclure produisait des rejets que le test exact ne
confirmait pas : ce n'était plus une borne mais un second solveur, plus faux que
le premier. Elle est donc restreinte aux **bridages et organes machine**.

Désactivée par défaut : voir §5.

### E4 — Test exact de l'outil complet

C'est le cœur. Dans le repère outil (origine au bec, `+z` = `d`), un point
obstacle `q` se réduit à un couple `(r, z)` :

```
z = q·d − tcp·d
r = √(|q − tcp|² − z²)
```

Pour chaque tronçon `[z₀, z₁] × [r₀, r₁]`, la distance signée point → tronçon
tronconique s'écrit en quelques opérations vectorisées. Le coût est
`O(N_points × N_tronçons)` **sans BVH, sans maillage**.

La distance radiale est corrigée par `cos α` (α = demi-angle du cône), ce qui la
**sous-estime** : une marge sous-estimée rejette parfois à tort, une marge
surestimée laisse passer une collision. Le sens de l'erreur est choisi.

#### Optimisation : TCP variable sans tenseur

Le TCP se déplace avec l'orientation dès qu'il y a un rayon de bec. Naïvement,
cela demanderait un tenseur `(N, M, 3)`. Or on n'a jamais besoin du vecteur,
seulement de ses projections :

```
z[n,m]  = p_n·d_m − tcp_m·d_m
|p_n − tcp_m|² = |p_n|² − 2 p_n·tcp_m + |tcp_m|²
```

Deux produits matriciels `(N,3)×(3,M)`. Coût mémoire `O(N·M)` au lieu de
`O(N·M·3)`.

#### Pré-filtre conique

La sphère de rayon `reach` (> 100 mm avec le nez de broche) garde tout ce qui se
trouve *derrière* le point de contact, c'est-à-dire dans la matière, où aucune
orientation ne peut aller. Comme toutes les orientations testées sont groupées
autour d'une direction moyenne, l'outil balaie en réalité un **cône**. Un point à
distance `D` n'est atteignable que si son angle à l'axe moyen est inférieur à
l'ouverture du faisceau élargie de `arcsin(r_max/D)`. Conservatif, et `O(N)`.

Mesure : 243 → 122 ms/point sur la scène C06.

#### Règles de pénétration

| | PIÈCE | BRUT | BRIDAGE | MACHINE |
|---|---|---|---|---|
| coupe | tolérance `cutting_allowance` | **autorisé** (c'est l'usinage) | interdit | interdit |
| col, tige, porte-outil, nez | interdit | interdit | interdit | interdit |

**Deux physiques, deux traitements.** Le dégagement du porte-outil se joue au
millimètre : le test discret conservatif y est parfaitement adapté, et son
pessimisme est une qualité. Le contact de l'arête avec la face usinée se joue au
centième et il est *voulu* — en fraisage de flanc, la coupe est tangente sur
toute sa longueur. Appliquer la même inflation aux deux ferait déclarer toute
passe de flanc « en collision avec la pièce ».

**Limite assumée** : ce mécanisme place la détection de gouge *fine* hors de
portée d'un test par nuage de points, dont la résolution est bornée par le pas
d'échantillonnage. La détection au centième exige des requêtes de distance
exactes sur le B-Rep (`BRepExtrema`) et est reportée à M3. Ce qui **est** garanti
ici : aucun organe non coupant ne pénètre la matière.

### E5 — Structuration

Les directions admissibles sont regroupées en **composantes connexes** sur le
graphe de la sphère. Chaque composante est un **cône d'accessibilité** : un
ensemble d'orientations parcourables continûment sans traverser de collision.
Passer d'un cône à un autre impose un dégagement — information que le planner
doit connaître et qu'un simple masque perdrait.

---

## Garantie conservative

Tout obstacle échantillonné avec un pas maximal `δ` est **inflaté de `δ`** avant
test. Le test discret devient un **majorant** du test exact :

- il peut refuser une orientation géométriquement admissible (faux négatif) ;
- il **ne peut pas** accepter une orientation en collision.

C'est la seule posture acceptable pour piloter une broche. Le test
`test_sample_surface_respects_spacing_bound` vérifie l'hypothèse d'espacement
dont tout ceci dépend.

---

## Diagnostic : chaque rejet porte un remède

| Motif | Remède proposé |
|---|---|
| `LEAD_LIMIT` | augmenter l'angle de lead, ou changer de stratégie |
| `AXIS_LIMITS` | rebrider la pièce, ou la réorienter sur le plateau |
| `SINGULARITY` | incliner la pièce au montage pour éloigner A de 0 |
| `COLLISION_CUTTING` | réduire la profondeur de passe ou le diamètre |
| `COLLISION_NECK` | outil à col dégagé plus long |
| `COLLISION_SHANK` | augmenter la longueur hors pince (jauge) |
| `COLLISION_HOLDER` | porte-outil plus élancé, ou jauge plus longue |
| `COLLISION_SPINDLE` | jauge nettement plus longue, ou accessibilité impossible |

Un rejet sans remède laisse l'utilisateur bloqué sans levier. C'est vérifié par
`test_rejection_always_carries_a_reason_and_a_remedy`.

---

## 5. Performance — mesures réelles

Poste de développement x86_64, scène C06 (13 455 obstacles, 642 directions
candidates dont ~87 après E1) :

| Configuration | Temps |
|---|---|
| boucle `check()` par direction | 98 ms/point |
| `check_many` vectorisé, pré-filtre sphérique seul | 243 ms/point |
| `check_many` + pré-filtre conique | **122 ms/point** |
| bornes E3 activées | +55 %, **0 gain** |

**Constat honnête** : les deux chemins (boucle et vectorisé) sont à 10 % l'un de
l'autre. Le goulot n'est pas la structure de boucle mais le **nombre
d'obstacles** `N`. Les bornes E3 sont désactivées par défaut : une optimisation
qui ralentit est une dette, pas un acquis. Elles sont conservées parce qu'elles
redeviennent utiles en finition (brut déjà enlevé, la borne supérieure peut
alors se déclencher).

**Extrapolation Pi 5** : 3 à 5× plus lent, soit 350 à 600 ms/point. Pour une
trajectoire de 5000 points, 30 à 50 minutes. **Inacceptable en production**,
suffisant pour ce jalon.

Plan d'optimisation, dans l'ordre, chacun conditionné à une mesure :
1. index spatial (grille de hachage / KD-tree) au lieu du sous-ensemble `O(N)` ;
2. calcul de l'accessibilité sur des **points-clés** épars, puis validation des
   points intermédiaires (la plupart héritent du cône de leurs voisins) ;
3. `float32` et traitement par blocs ;
4. noyau C/C++ derrière bindings — autorisé par ADR-001 / D11 **uniquement** sur
   profil mesuré sur le matériel cible, avec test différentiel obligatoire
   contre la version Python.

---

## Limites connues

- Le brut est considéré **intact** (hypothèse la plus conservative). Le suivi de
  matière enlevée arrive avec `stock_engine` M2 ; sans lui, l'ébauche
  multi-passes n'est pas représentable.
- Les volumes de collision **machine** (berceau, plateau) sont modélisés mais
  pas encore intégrés au champ d'obstacles : à ce jalon on ne teste que
  pièce/brut/bridages.
- La détection de gouge fine de l'arête de coupe est reportée (voir E4).
- Les bridages `custom_step` ne sont pas échantillonnés (boîtes seulement).
