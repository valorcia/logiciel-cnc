# ADR-003 — Jalon M3 : du STEP à la gamme validée

- **Statut** : Accepté (jalon M3)
- **Date** : 2026-09-12
- **Contexte** : complète ADR-001 et ADR-002.

> La licence produit reste **non tranchée** (ADR-001 / D10). C'est une décision
> commerciale ; elle ne bloque pas le développement et attend un ADR dédié.

---

## 1. Ce que M3 apporte

Pour la première fois la chaîne va de bout en bout **sans passe construite à la
main** : le planificateur décide seul des indexations, le slicer produit les
trajectoires, et chaque opération est validée couche par couche.

Mesure sur C02 (poche débouchante, pas 1,5 mm, couches de 2,5 mm) :

```
import contrôlé → brut voxel → 5 indexations candidates → ébauche +Z
  → 12/12 couches ACCEPTÉES, marge min 0,700 mm, 22 822 mm³ enlevés (52 %)
  → portes de sécurité : approved
  → génération de G-code : REFUSÉE (machine non calibrée)
```

| Limite M2 | Traitement M3 | État |
|---|---|---|
| Aucune gamme (`strategy_planner`, `subtractive_slicer`) | couverture gloutonne + tranchage voxel | **levée** |
| Import de STEP réels | diagnostic + réparation gardée + corpus dégradé | **levée** |
| Gouge fine : sondage | inchangé | **ouverte** |
| Performance sur Pi 5 | inchangé (pas de matériel) | **ouverte** |
| Poids non calibrés | inchangé (exige une machine) | **ouverte** |

---

## 2. Décisions

### D20 — Couverture gloutonne des indexations, assumée comme telle

Le problème est une **couverture d'ensembles** : quelles orientations, en
nombre minimal, voient toute la matière à enlever ? C'est NP-difficile.

Le glouton sur « volume atteignable » — fonction sous-modulaire — a la garantie
classique de 1 − 1/e. Mais ce n'est pas la raison principale de ce choix : il
est **déterministe et explicable**. On peut montrer à l'utilisateur pourquoi
telle indexation a été retenue et combien elle apporte. Un optimiseur global
serait meilleur de quelques pourcents et impossible à justifier devant une pièce
ratée.

Le filtre cinématique passe **avant** le classement, et non après : classer
d'abord donnerait un palmarès dont la tête est irréalisable.

### D21 — La singularité A → 0 est un problème de MOUVEMENT, pas de POSITION

Correction d'une erreur de M1/M2 qui avait une conséquence lourde.

Quand A s'annule, C devient indéterminé : une variation infinitésimale de l'axe
outil peut exiger 180° de plateau. Cela rend le suivi d'une trajectoire
**simultanée** impraticable — d'où la pénalité dans l'orientation solver.

Mais dans une opération **indexée**, C est bloqué pour toute la passe. Il n'y a
rien à suivre, donc rien de mal conditionné. `ik_best` refusait A = 0 dans tous
les cas, donc le planificateur ne proposait jamais ±Z — et laissait **intacte
toute poche ouverte vers le haut**, alors que c'est la prise la plus courante et
la plus rigide d'une XYZAC.

D'où `ik_best(..., allow_singular=True)`, employé par le planificateur seul.

### D22 — La zone interdite d'une couche se projette depuis le SOMMET

Le point le moins évident du slicer, et celui qui gouverne sa justesse.

La région interdite d'une couche n'est pas la projection de la pièce à **cette**
cote, mais sa projection **depuis cette cote jusqu'au sommet**. L'outil monte
vers la broche ; tout ce qui est protégé au-dessus du plan de coupe est sur son
chemin. Ne projeter que la couche courante ferait plonger l'outil dans une
contre-dépouille dès la première passe.

### D23 — Trois rayons, pas deux : interdit, utile, couvert

« Où l'outil peut-il aller », « où est-il utile » et « qu'a-t-il réellement
enlevé » ne demandent pas le même sens d'arrondi :

| | Arrondi | Conséquence d'une erreur de sens |
|---|---|---|
| interdit | **majoré** | une position douteuse acceptée ⇒ gouge |
| utile | **majoré** | une position rasante écartée ⇒ matière laissée |
| couvert | **minoré** | couverture fictive ⇒ faux sentiment de complétude |

Les confondre a un coût mesuré : en prenant le rayon **minoré** pour la zone
utile, la surépaisseur latérale de 2 mm devenait inatteignable — l'outil aurait
dû se placer à 3,9 mm de la pièce, donc hors du brut, et une position hors du
brut était jugée « inutile ». La moitié de la matière restait en place.

### D24 — Deux modèles conservatifs doivent PARTAGER leurs marges

Le slicer et le collision engine sont deux approximations conservatives
indépendantes. Si elles ne partent pas des mêmes marges, elles divergent sur une
frange de positions, et le validateur refuse des trajectoires que le slicer
croyait sûres. Divergence mesurée avant correction : **une pose sur 270, pour
0,226 mm** — exactement l'écart de marge entre les deux.

`slice_for_direction` prend donc `safety_clearance` en paramètre, et
`validate_roughing_progressive` **refuse** de valider un tranchage qui n'a pas
employé la sienne. Faire du slicer le plus conservatif des deux est le bon sens
d'arrondi : il perd un peu de matière, là où l'inverse produit un plan refusé.

Deux autres désaccords de discrétisation ont été corrigés sur le même principe :

- la dilatation 4-connexe répétée donne la boule **L1**, un losange plus PETIT
  que le disque dans les diagonales (l'offset (2,2) est à 2,83 du centre, donc
  dans le disque de rayon 3, mais à 4 en L1). Appliquée à la zone interdite,
  elle autorisait des positions qui gougent ;
- une dilatation de rayon R ne marque que les cellules dont le **centre** est à
  moins de R, alors qu'un centre d'outil peut se trouver n'importe où dans sa
  cellule. Il manquait la demi-diagonale de cellule : **108 poses sur 3 428**
  touchaient la paroi de la poche.

### D25 — Un chemin d'usinage n'est pas une suite de segments de coupe

Défaut trouvé par le validateur de balayage, et il était grave. Le zigzag
produisait des segments de coupe indépendants ; tout ce qui les relie était
implicite, et le validateur reliait les extrémités en ligne droite — droite qui
**traverse la matière** entre deux rangées. Les collisions signalées étaient
réelles : la trajectoire, telle qu'elle était décrite, passait dans la pièce.

`continuous_path` produit donc les liaisons explicitement : remontée au plan de
dégagement, déplacement, replongée. Avec deux raffinements mesurés :

| | points | dont liaison |
|---|---|---|
| segments isolés, liaisons implicites | — | *non modélisées* |
| remontée systématique, liaisons densifiées | 39 069 | 94,4 % |
| rangées chaînées quand le trajet reste valide | 22 017 | 86,2 % |
| liaisons émises comme **sommets** seulement | **4 057** | **25,4 %** |

Une liaison est une droite : la densifier au pas des points de coupe gonfle le
programme sans rien apporter. La subdivision d'un segment est le travail du
vérificateur de balayage, qui la calcule sur une borne prouvée — et la fait donc
mieux, et seulement quand il le faut.

### D26 — Le tronçon qui SUIT l'outil dans son propre canal

Règle physique qui manquait : un tronçon dont le rayon ne dépasse pas le rayon
de coupe tient forcément dans le passage ouvert par l'arête, dès lors que
l'outil progresse le long de son propre chemin. La tige d'une fraise 2 tailles
est dans ce cas — elle a **exactement** le diamètre de coupe.

Sans cette règle, le test discret la déclare en collision avec le brut à chaque
passe profonde : elle se trouve au bord exact du canal, et la moindre inflation
d'échantillonnage suffit à la faire toucher. Mesuré : 4 couches sur 12 refusées
pour 0,226 mm de pénétration d'une tige qui, en réalité, descend dans un trou
qu'elle remplit.

La condition sur le rayon est essentielle : un porte-outil ne tient pas dans le
canal, et reste un obstacle à part entière.

### D27 — Les bridages sont de la matière PROTÉGÉE

Le slicer ne connaît que deux choses : la matière à enlever, et la pièce à
conserver. Un bridage n'étant ni l'une ni l'autre, il planifiait des passes
jusqu'au fond du brut — c'est-à-dire **dans l'étau**. Le validateur les refusait
ensuite, à juste titre, avec des pénétrations de plusieurs millimètres.

Les marquer « protégés » est la bonne sémantique et pas un raccourci : un
bridage ne s'enlève pas, et il masque une direction exactement comme la pièce.
Les deux propriétés dont on a besoin sont déjà celles du masque protégé.

### D28 — La surépaisseur de finition est une distance MÉTRIQUE

La surépaisseur était réalisée par dilatation d'un nombre **entier** de voxels,
ce qui la quantifiait au pas de la grille. Une valeur demandée à 0,2 mm
devenait :

| pas de grille | surépaisseur réelle | facteur |
|---|---|---|
| 1,5 mm | 1,5 mm | ×7,5 |
| 1,0 mm | 1,0 mm | ×5 |
| 0,6 mm | 0,6 mm | ×3 |

L'utilisateur réglait sa finition, et c'était la résolution du solveur qui
décidait. La transformée de distance euclidienne respecte la valeur demandée,
avec une erreur bornée par un demi-voxel au lieu d'un voxel arrondi au-dessus.

### D29 — Import : diagnostiquer avant de réparer, et dire ce qu'on a changé

Trois règles, chacune motivée par un piège rencontré :

1. **On ne répare pas ce qui n'est pas cassé.** `ShapeFix` peut détériorer une
   géométrie saine en recousant des arêtes qui n'avaient rien demandé.
2. **Les défauts géométriques et les alertes de plausibilité sont distincts.**
   Une pièce de 2 mm est saine : ce n'est pas un défaut à réparer, c'est une
   question à poser (fichier en pouces ?). Les confondre faisait passer
   `ShapeFix` sur une pièce intacte.
3. **On vérifie que la réparation a réellement agi.** `ShapeFix` s'exécute sans
   broncher sur une forme qu'il ne sait pas réparer : un shell ouvert n'a pas de
   face manquante à inventer. Rapporter « réparation appliquée » laisserait
   croire le problème réglé. On compare l'état avant et après.

Un garde-fou de volume complète le tout : si la réparation déplace la matière de
plus d'un millième, elle est **refusée**. Ce n'est plus une réparation, c'est une
modification de la pièce — et ce n'est pas à un outil de la décider à la place
du concepteur.

Le test décisif pour notre usage ne se lit pas dans `BRepCheck` : un shell
ouvert est topologiquement « valide » et OCCT lui calcule même un volume, par
intégration sur ses faces. Ce qui trahit le défaut, c'est **l'absence de
solide** — sans quoi le lancer de rayons de la voxelisation compte un nombre
impair de traversées, et le moteur rend une gamme crédible et fausse.
`require_usable` refuse donc tôt et nomme le défaut.

### D30 — Performance : découper par blocs de points CONSÉCUTIFS

`check_many` amortit l'extraction du voisinage sur toutes les poses qu'on lui
donne, mais deux de ses pré-filtres — le cône et la coquille radiale par tronçon
— sont élargis de `spread`, l'étendue spatiale des TCP fournis.

Lui passer une trajectoire entière est donc contre-productif : sur une couche
d'ébauche, les poses couvrent 60 mm, le `spread` atteint 35 mm, et les deux
pré-filtres ne prunent plus rien. **4,1 s pour 368 poses.**

Les points d'un chemin étant ordonnés, des blocs de points **consécutifs** sont
spatialement compacts. On retrouve un `spread` de quelques millimètres, et donc
tout l'effet des pré-filtres.

Deux autres optimisations de même nature :
- le balayage traitait un segment à la fois, réextrayant son voisinage pour une
  poignée de poses : la validation d'une ébauche ne se terminait pas. Il
  interpole maintenant tous les segments puis teste par paquets ;
- seule la **peau** de la matière protégée est envoyée au moteur de collision.
  Un point enfoui dans la pièce ne sera jamais le plus proche de l'outil, mais
  il était testé comme les autres : 21 622 points contre 7 000 pour la peau.

---

## 3. Ce que M3 ne lève pas

| Limite | Pourquoi | Levée par |
|---|---|---|
| **Machine non calibrée** | pivots, courses et jeux sont provisoires | une machine + `assembly_calibration` |
| Gouge fine : sondage | le coût exact interdit de tout tester | un critère de sélection des poses à vérifier |
| Perf. jamais mesurée sur Pi 5 | pas de matériel ici | la cible embarquée |
| Poids d'orientation non calibrés | exige des essais de coupe | qualification |
| Finition (contour-parallèle, passes 5 axes) | M3 ne produit que de l'ébauche indexée | M4 |
| Tournage | `turning_engine` détecte, ne génère pas | M4/M5 |

La calibration est désormais **le** verrou du post-processeur, et il n'est pas
logiciel. Sur une cinématique table/table, l'erreur de position des pivots se
propage directement à la pièce.

**±0,02 mm reste un objectif de qualification physique**, inchangé depuis M1.

---

## 4. Performance mesurée (x86_64)

| Étape | Temps |
|---|---|
| voxelisation d'une pièce (pas 0,8 mm) | 0,1 – 0,2 s |
| visibilité directionnelle | 0,02 s / direction |
| tranchage d'une direction | 0,5 – 1,5 s |
| simulation d'enlèvement | 0,5 – 4 s |
| **validation progressive (12 couches, 4 000 points)** | **≈ 100 s** |

La validation domine, et c'est cohérent : elle exécute les quatre vérifications
sur chaque couche, balayage compris. Elle reste le poste à optimiser, et
l'extrapolation ×3–5 sur Pi 5 la rendrait inutilisable en interactif. Pistes
identifiées, non encore mesurées : validation incrémentale (ne revérifier que ce
qui change d'une couche à l'autre), et noyau natif derrière bindings — autorisé
par ADR-001 / D11 sur profil mesuré, avec test différentiel obligatoire.
