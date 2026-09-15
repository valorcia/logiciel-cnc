# ADR-014 — Séparer la peau des cavités, puis enchaîner volume → outil → orientation

## Contexte

ADR-013 a fait de la matière à enlever un ensemble de **volumes**, chacun essayé
avec plusieurs outils. La mesure qui a suivi a montré que le chiffre rendu ne
voulait rien dire.

Sur une pièce prismatique, le brut enveloppe la pièce d'une **peau continue** —
2 mm de marge sur chaque face — et cette peau relie toutes les cavités en **un
seul bloc**. Mesure sur C02, brut à 2 mm :

| | volume | Ø 10 mm | Ø 6 mm | Ø 3 mm |
|---|---|---|---|---|
| un seul volume « indivis » | 47 669 mm³ | 41 % | — | 43 % |

Deux points d'écart entre deux outils que tout sépare, parce que la peau
dominait le compte et qu'aucun des deux n'y entrait.

Et le verdict s'arrêtait là : on savait quel outil entrait dans un creux, mais
pas s'il pouvait y **arriver**. Les deux questions étaient posées séparément,
donc l'opérateur recevait deux refus sans savoir lequel comptait.

## Décision

### 1. La peau se sépare des cavités par l'enveloppe convexe

Un creux est une **concavité** de la pièce, donc de la matière enlevable située
à l'intérieur de l'enveloppe convexe de la pièce :

    cavités = enlevable ∩ conv(pièce)        peau = enlevable − conv(pièce)

C'est **exact et sans paramètre** : l'enveloppe convexe d'un solide est le plus
petit convexe qui le contient, et un solide n'a de creux que là où il s'en
écarte. Une pièce déjà convexe n'a donc aucune cavité, et le module le dit
plutôt que d'en inventer — C01, C14 et C20 rendent **zéro creux**.

Une fois la peau retirée, les cavités se séparent d'elles-mêmes : le chemin qui
reliait deux poches passait par la peau.

Le sens de l'erreur reste favorable : l'enveloppe est construite sur les
**centres** des voxels de la pièce, donc plus petite d'un demi-voxel. La bordure
d'une cavité, à sa bouche, bascule donc du côté « peau » — et c'est sa partie la
plus **ouverte**, celle où le gros outil entrait le plus facilement. La fraction
attribuée à un gros outil ne peut qu'être sous-estimée.

Ce que le critère ne fait pas : il est convexe, donc il ne distingue pas un creux
fermé d'un décrochement ouvert. Le rentrant d'une pièce en L est compté comme une
cavité. Ce n'est pas un défaut à corriger en douce — c'est le sens du mot :
le module nomme les **concavités**, pas les poches fermées.

### 2. Un outil entre par la bouche, pas en tenant tout entier dans le creux

`ouverture` confinait la boule **dans** le volume. Une poche ouverte se voyait
donc rogner toute la couronne du haut, comme si de la matière la couvrait.

`portee_outil` fait circuler la boule dans l'espace **libre** — tout sauf la
pièce à conserver, l'air au-dessus compris. C'est le modèle juste : l'outil
arrive de l'extérieur, et la matière au-dessus de lui aura déjà été enlevée
quand il passera.

### 3. Le majorant est celui du FOND, et il se tait quand il ne mesure rien

`rayon_inscrit_max_mm` mesurait la plus grosse boule qui **tient** dans le
volume. C'est devenu faux le jour où l'outil a eu le droit de circuler hors du
volume : sur la peau du brut, épaisse de 2 mm, la boule inscrite faisait
Ø 3,5 mm pendant qu'une Ø 10 en enlevait 100 % en roulant dessus.

Le remplacer par « le plus gros outil qui touche ce volume quelque part » n'a
rien arrangé : sur un volume ouvert cela rendait Ø 134 mm, c'est-à-dire
exactement **deux fois le rembourrage du tableau de calcul**. Un nombre qui
bouge quand on change une constante d'implémentation ne mesure pas la pièce.

Seul le **fond** borne quelque chose. `rayon_au_fond_mm` est donc le plus gros
outil qui atteint le point le plus profond, plafonné à Ø 50 mm (`PLAFOND_OUTIL_MM`),
au-delà duquel il rend `inf` — lu « fond à ciel ouvert ».

### 4. L'enchaînement nomme l'étape qui bloque

`strategy_planner.creux` pose les trois questions dans l'ordre :

1. **quel volume** — la décomposition trouve un creux, ou n'en trouve pas ;
2. **quel outil** — aucun outil de la gamme n'y entre, et alors il n'y a rien à
   orienter : la question suivante ne se pose même pas ;
3. **quelle orientation** — l'outil retenu rentre, mais le porte-outil, le nez
   de broche ou les courses linéaires s'y opposent.

Nommer l'étape qui bloque, c'est nommer ce qu'il faut **changer** : un outil plus
fin, un autre bridage, ou une seconde prise de pièce. « Non usinable » tout court
n'indique aucune de ces trois actions.

### 5. La question posée au solveur n'est pas celle d'une surface

Première version, première mesure : la poche de C02 se faisait refuser avec
« 8 des 8 points sondés ne sont atteignables par AUCUNE orientation », en
accusant le plateau de la machine. C'était faux.

`decide_indexed_pass` cherche une orientation qui mette le **bec** de l'outil
face à chaque point. C'est la bonne question pour une passe de finition sur une
surface. Ce n'en est pas une pour un creux : une poche a un fond qui regarde en
haut et quatre flancs à 90° du fond. Aucune orientation ne les met tous face au
bec, et il n'en manque aucune — les flancs se coupent par le **flanc**.

Un creux a donc une direction à lui : celle de sa **bouche**, mesurée comme la
part du creux que `reachable_from` voit depuis chaque candidate. Cette direction
est ensuite vérifiée par `verify_direction`, qui rend un motif **par point**, et
le motif fait toute la différence :

- `LEAD_LIMIT` — le point regarde ailleurs : une autre orientation, ou le flanc
  de l'outil. Ce n'est pas un blocage ;
- `COLLISION_CUTTING` — le tronçon coupant touche la pièce. C'est son travail.
  Sur le fond d'une poche, tout point à moins d'un rayon du flanc est dans ce
  cas — 8 points sur 60 mesurés sur C02. Le même piège avait déjà été tendu au
  portillon de collision, qui écartait la meilleure indexation de C02 **pour
  avoir coupé** ;
- tout le reste — col, tige, porte-outil, nez de broche, organes machine,
  butées d'axes — bloque, et est compté et nommé séparément.

### 6. À visibilité égale, c'est la vérification qui tranche

Une rainure débouchante se voit à 100 % de deux directions au moins : par le
dessus et par le bout. Les deux « voient tout », et pourtant l'une finit son fond
au bec et l'autre ne finit rien. Mesure sur C04, rainure de 8 × 40 × 35 mm :
départagées par l'ordre de la liste, le moteur retenait le bout et concluait
« ce creux ne se prend qu'au flanc ».

Toutes les directions à moins de 5 points de la meilleure sont donc vérifiées,
et on garde celle qui finit le plus de points au bec, à blocages égaux.

### 7. L'outil retenu est celui de l'ÉBAUCHE

`outil_le_plus_gros` exige de vider 98 % du creux : sur la poche de C02 il
retenait donc Ø 3 mm, seul à y arriver. Une Ø 3 dans une poche de 30 mm de
large, c'est une heure de travail pour ce qu'une Ø 10 fait en quelques minutes.

`outil_d_ebauche` est le plus gros qui **entre et atteint le fond** — aucun seuil
arbitraire, et son majorant est exactement `rayon_au_fond_mm`. La reprise suit,
et seulement si elle en prend davantage.

## Défaut de voxelisation trouvé au passage

La séparation a fait apparaître **28 fausses colonnes traversantes** de
1 × 1 × 25 mm dans C02, présentées comme 28 creux à usiner. Ce n'était pas la
séparation : c'était `solid_mask`, et c'était ancien.

Le remplissage par parité tirait le rayon du **centre** du voxel. La face
inférieure d'un bloc se maille en deux triangles dont l'arête commune est la
**diagonale**, et tous les centres de voxels d'une grille au pas entier tombent
dessus : le test barycentrique répondait « touché » des deux côtés, la colonne
comptait trois traversées au lieu de deux, et le code laissait tomber la
dernière. La colonne se vidait sur toute la hauteur de la pièce.

Le rayon est maintenant décalé de 10⁻⁷ et 3,7·10⁻⁷ pas — deux valeurs
**différentes**, sans quoi le rayon resterait sur la diagonale `x = y`. Mesure du
gain, sur le volume vrai :

| pièce | pas | avant | après |
|---|---|---|---|
| C02 | 1,0 mm | −1,19 % | **0,00 %** |
| C02 | 0,25 mm | −0,29 % | **0,00 %** |
| C19 | 1,0 mm | −1,36 % | **0,00 %** |
| C19 | 0,25 mm | −0,31 % | **0,00 %** |

Deux tests ont dû être réécrits : ils étaient calibrés sur les valeurs biaisées,
et l'un d'eux tolérait 6 % d'écart au volume vrai là où la surépaisseur qu'il
mesurait n'en vaut que 4 — le défaut qu'il cherchait se serait caché dedans.

## Conséquences

### Le chiffre par outil discrimine, et il discrimine par creux

| pièce | creux | outil d'ébauche | Ø 10 / 6 / 3 |
|---|---|---|---|
| C02 poche droite | 30 × 30 × 20 | Ø 10, reprise Ø 6 | 90 / 95 / 100 % |
| C04 rainure profonde | 8 × 40 × 35 | Ø 6 | 9 / 97 / 100 % |
| C05 ailettes (canal étroit) | 70 × 10 × 45 | Ø 6 | 10 / 98 / 100 % |
| C05 ailettes (2 autres) | 70 × 13 × 41 | Ø 10 | 97 / 98 / 100 % |
| C09 quatre trous | 15 × 10 × 10 | Ø 6 | 4 / 78 / 99 % |
| C07 gorge en T | 26 × 50 × 30 | Ø 6 | 41 / 96 / 100 % |

Sur C05, le canal étroit refuse la Ø 10 que les deux autres acceptent. C'est
exactement la décision que l'opérateur doit prendre, et elle n'était pas
visible avant : les trois canaux et la peau ne faisaient qu'un seul chiffre.

### L'enchaînement complet, sur les 20 pièces du corpus

**23 creux** trouvés sur 20 pièces (C01, C14 et C20 n'en ont aucun, et c'est
juste — les deux premières sont convexes, la troisième a un détail plus fin que
le pas de grille). Le calcul prend **1 à 11 s** par pièce.

| verdict | creux | exemples |
|---|---|---|
| **se vide** | 12 | C02 (A = 0), C06 contre-dépouille (A = −65°), C09 quatre trous (4 orientations différentes), C11 cavité sphérique, C13 gorge torique |
| **aucune orientation** | 8 | C04 et C16 (la tige touche → jauge plus longue), C05 ×2 (l'outil touche un organe machine → rapprocher du centre du plateau), C12 (le porte-outil touche), C10 (butée d'axe) |
| **au flanc seulement** | 3 | C07 gorge en T, C18 poche à fond bombé, C19 l'entre-deux des deux solides |
| **aucun outil n'entre** | 0 | — |

Aucun refus muet : chaque refus nomme sa cause **en français** et l'action qui
le lèverait. C06 est le cas qui justifie la machine : une contre-dépouille que
rien n'atteint à plat se vide à Ø 10 mm en basculant le berceau à −65°.

Le cas C09 montre ce que la séparation apporte : quatre trous sur quatre faces
donnent **quatre creux**, chacun avec **son** orientation (A = −90 / C = 90,
A = −90 / C = 0, A = −95 / C = −180, A = −96 / C = −90). Mélangés à la peau,
c'était un seul volume et un seul chiffre.

## Ce qui reste hors de portée

- **Le fraisage en roulant** n'est pas décidé. Un creux dont aucun point de bord
  ne se finit au bec — une poche conique, par exemple — reçoit l'étape `flanc`,
  qui est un aveu du moteur et non un refus de la pièce.
- **Un détail plus fin que le pas de grille est invisible.** Mesure sur C20, dont
  la gravure disparaît entièrement à 1 mm : la pièce s'y voxélise en bloc plein,
  et le module rend « aucun creux » — la bonne réponse à cette résolution, et non
  une réponse à la pièce. Rien ne le signale encore à l'opérateur.
- **Une seule orientation par creux.** Les points qui regardent ailleurs sont
  comptés et nommés, mais la seconde orientation n'est pas cherchée.
- **La trajectoire elle-même n'est pas produite.** On sait quel outil, depuis
  quelle orientation, et ce qui bloque — pas le parcours.
