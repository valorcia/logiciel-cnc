# ADR-018 — L'ordre des passes

## Contexte

ADR-017 a ramené le transport du corpus de 20 à 15 mètres en abaissant chaque
liaison à la hauteur la plus basse qui dégage. Sur une poche compacte c'est
spectaculaire — C03 passe de 37 à 87 % de chemin coupant.

**Sur le dôme de C10, le gain était de 4 %.** Et C10 disait pourquoi : ses
117 liaisons, pour un seul creux, vont d'une région à l'autre **par-dessus le
dôme lui-même**, qui est de la matière protégée. Aucune hauteur plus basse
n'existe — le calcul de hauteur n'avait rien à trouver.

Ce qui coûte là n'est pas la hauteur d'une liaison. C'est leur **nombre et leur
longueur**, donc l'ordre dans lequel on visite les régions.

## Décision

Réordonner les passes **à l'intérieur d'une couche**, par plus-proche-voisin
puis 2-opt.

### Dans une couche, et rien d'autre

L'ordre des couches est une **contrainte physique** — on ne peut pas usiner la
couche 5 avant la 4 — et le mélanger à une question de trajet serait confondre
une règle avec une préférence.

Le point de départ de chaque couche est la **fin** de la précédente : c'est
gratuit, et cela raccourcit aussi la liaison entre deux couches.

### Retourner une passe : seulement en zigzag

Parcourir une passe dans l'autre sens raccourcit souvent le trajet. Mais le sens
de parcours est le sens de **coupe**, et le balayage `unidirectionnel` existe
précisément pour le garder constant — l'avalant et l'opposition n'usent pas
l'outil de la même façon, et quelqu'un qui a choisi ce mode l'a choisi.

Le retournement n'est donc autorisé qu'en `zigzag`, où l'alternance est déjà
dans le contrat. En `unidirectionnel`, le 2-opt se contente de **déplacer** des
passes sans changer leur sens — moins efficace, et c'est le prix d'un sens de
coupe constant.

Le détail qui compte dans le 2-opt : renverser un morceau du tour **retourne
aussi chaque passe qu'il contient**. Parcourir un bout de chemin à l'envers,
c'est entrer dans chaque passe par son autre bout. L'oublier donnerait un coût
calculé sur un tour qui n'est pas celui qu'on émettrait, et le gain annoncé
serait faux.

### Ce que la méthode vaut, et ce qu'elle ne prétend pas

Plus proche voisin + 2-opt est le couple classique du voyageur de commerce, et
il **n'est pas optimal**. Sur des dizaines de passes par couche, l'optimum exact
coûterait des heures pour quelques pour cent — et ces quelques pour cent se
perdraient dans les approximations de tout le reste de cette chaîne.

Ce qui est garanti : le résultat n'est **jamais pire** que l'ordre d'origine.
Celui-ci est évalué en premier, et on ne le quitte que pour plus court.

Le coût optimisé est la distance **à vol d'oiseau** entre les bouts, pas la
longueur de la vraie liaison en trois morceaux : la hauteur de celle-ci dépend
de la matière, donc de l'ordre, donc d'elle-même. La distance entre les bouts en
est le terme dominant et le seul qui ne dépende pas du reste.

## Mesures

Les deux leviers, cumulés, sur les 7 creux du corpus qui reçoivent un parcours :

| pièce | transport | part coupante |
|---|---|---|
| C03 poche conique | 446 → **38 mm** (−91 %) | 37 → **87 %** |
| C11 cavité sphérique | 974 → **213 mm** (−78 %) | 63 → **89 %** |
| C02 poche droite | 566 → **160 mm** (−72 %) | 70 → **89 %** |
| **C10 dôme convexe** | 10 481 → **3 035 mm** (−71 %) | 32 → **62 %** |
| C06 contre-dépouille | 2 366 → 823 mm (−65 %) | 62 → 83 % |
| C15 révolution hors axe | 4 899 → 1 856 mm (−62 %) | 32 → 56 % |
| C13 gorge torique | 329 → 198 mm (−40 %) | 27 → 38 % |
| **total** | **20 061 → 6 323 mm (−68 %)** | **42 → 70 %** |

**245 liaisons vérifiées une à une au balayage complet de l'outil : 0 en
faute.**

### La part de chaque levier, sans la compter deux fois

Sur C10, mesuré séparément :

| | transport |
|---|---|
| ni ordre ni abaissement | 10 481 mm |
| **ordre seul** | 6 851 mm (−37 %) |
| ordre **et** abaissement | 3 035 mm (−71 %) |

Les deux se renforcent : réordonner produit des sauts courts, et un saut court
a plus de chances de trouver une hauteur basse. Attribuer à l'un le gain des
deux serait compter deux fois.

Coût : 0,3 à 2,3 s par creux, ordre et abaissement compris.

## Ce que ce module ne fait pas

- il ne réordonne **pas les couches** entre elles, ni les creux entre eux ;
- il n'est **pas optimal** et ne le prétend pas ;
- il ne tient pas compte de l'**usure** ni de l'engagement de l'outil : deux
  ordres de même longueur ne chargent pas forcément la fraise pareil ;
- la distance optimisée est à vol d'oiseau, pas la vraie liaison.
