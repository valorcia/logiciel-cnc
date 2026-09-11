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
E0  génération des candidats      642 directions (icosphère niv. 3) + germes analytiques
E1  filtre géométrique local      face arrière + angle de lead maximal
E2  filtre cinématique            butées A/C, singularité, 2 branches IK
E3  encadrement à deux bornes     (désactivé par défaut — voir §5)
E4  test exact outil complet      par tronçon, coquille radiale, vectorisé NumPy
E4b garde machine                 berceau, plateau, carters + courses linéaires
E5  structuration                 composantes connexes → cônes d'accessibilité
```

> **M2** : E0 reçoit des germes analytiques, E4 une coquille radiale par tronçon,
> et E4b est nouveau. Voir [ADR-002](../adr/ADR-002-jalon-M2.md).

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

#### Germes analytiques (M2)

Une grille uniforme peut **manquer par construction** un ensemble admissible
étroit. Le cas concret : sur une face usinée en bout à la fraise à bout droit,
l'ensemble admissible est une lamelle de quelques degrés autour de la normale —
incliner l'outil enfonce son talon. Un pas de 8,6° n'a aucune raison d'y placer
un sommet.

On ajoute donc la **normale exacte**, la direction lead/tilt souhaitée, et un
éventail fin (±8°, 3 anneaux × 10) autour d'elles. Coût : ~31 candidats de plus
sur ~640. Raffiner toute la sphère coûterait ×4 par niveau pour un problème
purement local.

Propriété garantie : les germes **ajoutent** des candidats, ils n'en retirent
aucun.

⚠️ Les germes ne sont pas des sommets de grille — ils sont rattachés au sommet
le plus proche. L'intersection d'ensembles de la segmentation 3+2 devient donc
une *heuristique de proposition*, et l'orientation qu'elle retient est
**re-vérifiée exactement** en chaque point du segment.

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

### E4b — Garde machine (M2)

Une orientation parfaitement dégagée côté pièce peut envoyer le nez de broche
dans le berceau, ou l'outil sous le plateau. Ne pas le tester laisse passer
précisément les collisions les plus coûteuses.

**L'idée qui rend ce test bon marché** : dans le repère MACHINE, l'axe de
l'outil vaut invariablement `+Z` — c'est la définition d'une broche à axe fixe.
Inutile donc de transporter les organes machine dans le repère pièce pour chaque
orientation ; on transporte le TCP vers le repère machine, où l'outil est
toujours droit.

Seuls bougent les volumes portés par le berceau (`Rx(A)`) et par le plateau
(`Rx(A)·Rz(C)`). Les courses linéaires X/Y/Z sont vérifiées au même endroit.

Deux motifs de rejet distincts, avec deux remèdes distincts :
`MACHINE_COLLISION` (rapprocher la pièce du centre du plateau) et
`MACHINE_TRAVEL` (repositionner la pièce).

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
| `check_many` + pré-filtre conique | 122 ms/point |
| **+ coquille radiale par tronçon (M2)** | **55 ms/point** |
| bornes E3 activées | +55 %, **0 gain** |

**Coquille radiale par tronçon (M2)** — la mesure M1 disait que le goulot était
le nombre d'obstacles `N`, pas la structure de boucle. L'observation qui a
débloqué : `|p − tcp|` ne dépend pas de la direction testée. Un point ne peut
donc atteindre le tronçon `[z₀,z₁]×[r₀,r₁]` que si

```
z₀ − inf − spread  ≤  |p − tcp|  ≤  √((z₁+inf)² + (r_max+inf)²) + spread
```

Chaque tronçon ne voit qu'une coquille du nuage, calculée une fois pour toutes
les orientations. L'arête de coupe (z ≤ 20 mm, r = 3 mm) ne voit plus qu'une
petite boule là où elle balayait les mêmes milliers de points que le nez de
broche. **×2,2 mesuré, résultats identiques.**

**Index spatial adaptatif (M2)** — une grille de hachage uniforme, utilisée
seulement quand la requête est sélective (`volume_sphère < 15 %` du volume de
scène). Sur une pièce plus petite que la portée de l'outil : ×1,5 seulement, la
sphère couvrant tout le nuage. Sur une pièce de 600 mm : **×48** (3,4 ms contre
162 ms). Le critère est mesurable, pas doctrinal.

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

- ~~Brut considéré intact~~ → **levé en M2** : `MaterialState` suit la matière
  restante sur grille voxel. Trois modes : `intact` (conservatif), `finished`
  (ébauche supposée faite — optimiste, réservé à l'étude d'une passe de
  finition), ou état réel issu de la simulation des passes précédentes.
- ~~Volumes machine non intégrés~~ → **levé en M2** (E4b).
- ~~Bridages `custom_step` non échantillonnés~~ → **levé en M2**
  (`Fixture.step_path`).
- La détection de gouge fine reste un **sondage** : `verify_gouge_exact` est
  exact sur les poses testées, mais son coût interdit de tout tester. Une gouge
  détectée est certaine ; une absence de gouge sur l'échantillon ne prouve rien
  entre les échantillons.
- Performance **jamais mesurée sur Pi 5** : l'extrapolation ×3–5 reste une
  extrapolation.
