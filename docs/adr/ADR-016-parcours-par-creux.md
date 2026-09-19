# ADR-016 — Le parcours par creux

## Contexte

L'atelier s'arrêtait à *« ce creux se vide à la Ø 10 mm, par sa bouche, à
A = 0°, C = 0° »*. Il ne disait pas **par où l'outil passe** — la dernière
marche entre un analyseur et un logiciel d'usinage.

Sans parcours : pas d'animation d'un creux (l'image montrait un outil posé à
l'entrée), pas de temps de cycle par creux, et surtout **rien à optimiser** côté
transport, qui pèse 71 % du temps de cycle mesuré.

## Décision

Rien n'est réinventé. `slice_for_direction` sait trancher et zigzaguer,
`continuous_path` sait relier les passes sans traverser la matière — un défaut
déjà trouvé à la validation et corrigé là-bas. Il manquait de pouvoir
**restreindre le tranchage à un creux**, et de l'appeler avec l'outil et la
direction que `decider_creux` a déjà trouvés.

### Le masque restreint la CIBLE, pas l'ÉTENDUE

`slice_for_direction` prend un `masque`. Il restreint ce que la coupe vise ; il
ne touche ni à ce qui est **interdit** — la pièce protégée reste obstacle
partout — ni à l'**étendue**, qui sert au plan de dégagement.

Restreindre l'étendue aussi aurait produit un parcours qui remonte juste
au-dessus de sa poche et percute la peau du brut restée en place tout autour :
un dégagement qui dégage d'un creux et rentre dans un autre.

Ce que ce masque suppose et qu'il faut dire : la matière enlevable **hors du
masque ne bloque pas**. C'est le même choix que `reachable_from` — elle sera
partie quand on arrivera là — mais il devient ici une hypothèse d'**ordre**. Le
séquencement des creux entre eux n'est décidé par personne.

### Ce que le parcours enlève est MESURÉ, pas estimé

Le trancheur a son propre chiffre, `uncovered_mm3`, calculé avec un rayon
volontairement **minoré** — demi-diagonale du voxel et de la cellule en moins —
pour ne jamais s'attribuer de couverture fictive. C'est le bon sens d'arrondi
là-bas, et un mauvais chiffre à afficher : sur la poche de C02 il annonce 58 %
quand l'outil en prend 70.

`enleve_par_passage` passe donc l'outil sur une **copie** de la matière et
compte la différence avant/après. La différence, et non le reste seul : une
partie du creux peut être déjà enlevée quand ce parcours commence, et la compter
comme laissée par lui serait lui reprocher le travail d'un autre.

### Le reste se partage en TROIS tas, parce qu'il appelle trois gestes

| tas | ce que c'est | quoi faire |
|---|---|---|
| **non vu** | ce que cette bouche ne voit pas | une autre orientation, ou une seconde prise |
| **hors de portée** | les angles plus serrés que le rayon | un outil plus fin |
| **surépaisseur** | la marge que l'ébauche laisse volontairement | rien — la finition la prend |

Un seul « il en laisse 30 % » ferait chercher un outil plus fin devant une poche
que la finition allait terminer.

## Deux défauts trouvés en mesurant

### 1. Deux dénominateurs qui ne se comparaient pas

Sur la poche conique de C03, que la direction ne voit qu'à 33 %, le rapport
« ce qui reste sur **tout** le creux » ÷ « ce que la coupe **vise** » donnait
**« enlève 0 % »** pour un parcours de 344 points qui coupait pour de bon.

Même famille que les douze défauts précédents du projet : une grandeur divisée
par une autre qui ne mesure pas la même chose. `ParcoursCreux` n'a plus qu'un
seul dénominateur, le volume du creux, et un test vérifie que les quatre parts
ne dépassent jamais 100 %.

### 2. Un parcours vide, sans un mot

Sur les quatre trous de C09, le parcours sortait à **zéro point** sous une ligne
marquée « se vide ». Le refus était vrai ; le silence était fautif.

La cause est la marge que le trancheur s'impose pour ne jamais proposer une
position que le contrôle de gouge refuserait :

    marge = ½·pas·√3  +  garde  +  ½·pas·√2

soit **1,9 mm à 1 mm de pas**. Une fraise de Ø 6 mm dans un trou de Ø 10 a
1,0 mm de jeu au rayon : il ne reste pas une cellule où poser un centre d'outil.

Le parcours le dit maintenant, avec les deux leviers — un outil plus fin, ou une
grille plus fine, puisque **1,6 de ces 1,9 mm viennent du pas** et fondent avec
lui (0,7 mm à 0,25 mm de pas). La marge n'a pas été desserrée : la desserrer
ferait diverger le trancheur et le contrôle de gouge, ce que le projet a déjà
payé une fois.

`marge_de_tranchage` **reproduit** un calcul écrit dans `slice_for_direction`,
qui ne le rend pas. Un test compare les deux, pour que le jour où l'un bouge,
l'autre ne mente pas en silence.

## Mesures sur le corpus

11 creux sur 23 reçoivent un parcours ; les 12 autres avaient déjà été refusés
en amont (orientation, flanc). Calcul : **0,1 à 0,9 s par creux**.

| pièce | creux | outil | points | couches | chemin qui coupe | enlevé (outil) |
|---|---|---|---|---|---|---|
| C02 poche droite | 30×30×20 | Ø 10 | 848 | 12 | 70 % | 70 % (90 %) |
| C03 poche conique | 40×40×20 | Ø 10 | 344 | 12 | 37 % | 18 % (74 %) |
| C06 contre-dépouille | 60×27×28 | Ø 10 | 2 746 | 10 | 62 % | **81 %** (88 %) |
| C10 dôme | 58×58×15 | Ø 10 | 3 122 | 9 | 32 % | 67 % (82 %) |
| C11 cavité sphérique | 40×40×20 | Ø 10 | 1 039 | 11 | 63 % | 77 % (92 %) |
| C15 révolution hors axe | 66×36×11 | Ø 10 | 1 929 | 16 | 32 % | 57 % (87 %) |
| C09 quatre trous | 15×10×10 | Ø 6 | **0** | 0 | — | marge de tranchage |
| C13 gorge torique | 36×36×10 | Ø 10 | 102 | 4 | 27 % | 2 % (50 %) |
| C17 face quasi horizontale | 50×52×2 | Ø 10 | 25 | 1 | 100 % | 14 % (54 %) |

La part du chemin qui coupe va de **27 % à 100 %** selon la forme — contre
24-29 % sur une gamme entière. Sur un creux compact elle est bonne ; sur un
creux plat et large (C10, C15, C17) le transport domine déjà. C'est le chantier
suivant, et ce tableau est sa mesure de départ.

## Ce que ce parcours n'est PAS

- **Il n'est pas vérifié en collision.** `decider_creux` a vérifié
  l'orientation sur les points de bord ; les positions de ce chemin-ci n'ont pas
  été passées au solveur. Le tranchage les garantit sans gouge sur la pièce
  **protégée**, ce qui n'est pas la même chose que sans collision de
  porte-outil.
- **Il ne dit pas dans quel ordre** vider les creux entre eux.
- **Ce n'est pas du G-code**, et rien ici ne sort vers une machine.
