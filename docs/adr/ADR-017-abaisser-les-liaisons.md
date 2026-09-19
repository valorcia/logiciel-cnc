# ADR-017 — Abaisser les liaisons

## Contexte

Sur une gamme complète, **24 à 29 % seulement** du temps se passe à couper. Le
reste — 140 838 mm de rapides, 1 197 dégagements — est du transport. C'est le
plus gros levier de temps mesuré du projet, et il n'avait jamais été attaqué.

`continuous_path` relie deux passes en remontant au **plan de dégagement**,
c'est-à-dire au-dessus de toute la matière. C'est la stratégie la plus sûre qui
soit, et elle a été adoptée pour une bonne raison : la version d'avant reliait
les extrémités en ligne droite, et cette droite traversait la matière entre deux
rangées.

Mais elle est sûre **partout**, y compris là où il n'y a plus rien. Mesure sur
la poche de C02 : 566 mm de liaisons pour 1 338 mm de coupe, et ces 566 mm sont
essentiellement onze aller-retours au plan de dégagement entre douze couches —
alors que l'outil reste dans la même poche, déjà vidée au-dessus de lui.

## Décision

Pour chaque liaison, calculer la hauteur la plus basse à laquelle l'outil
**complet** — bec, goujure, col, tige, porte-outil, nez de broche — ne touche
plus rien, et s'y tenir. Le plan de dégagement reste le **plafond** : ce module
ne peut pas rendre une liaison pire que celle qu'il remplace.

### La hauteur se calcule, elle ne s'essaie pas

Le tronçon d'outil `i` occupe, quand le bec est à la hauteur `h`, la tranche
`[h + z0ᵢ, h + z1ᵢ]` à moins de `rᵢ` de l'axe. Si la matière présente dans ce
couloir-là monte au plus jusqu'à `Mᵢ`, alors `h > Mᵢ − z0ᵢ` suffit à l'en
sortir :

    h = maxᵢ (Mᵢ − z0ᵢ) + marge

Un seul balayage des voxels par liaison donne les `Mᵢ`.

La première version procédait par essais successifs — huit hauteurs, un balayage
complet de l'outil à chacune. Elle donnait le même résultat en **9,1 s** par
creux contre **0,2 s** pour celle-ci.

### La matière est suivie au fur et à mesure

Chaque passe de coupe est retirée d'une **copie** avant que la liaison suivante
ne soit mesurée. C'est ce qui permet de descendre dans une poche qu'on vient de
vider — et ce qui interdit de descendre dans une poche qu'on n'a pas encore
ouverte.

### Ce qui est garanti, et ce qui ne l'est pas

Une liaison a trois morceaux, un seul change :

| morceau | ce que c'est | garanti ? |
|---|---|---|
| montée | verticale, à l'aplomb du dernier point coupé | inchangée |
| **traversée** | horizontale, à la hauteur calculée | **oui, c'est elle qu'on prouve libre** |
| plongée | verticale, jusqu'au premier point de la passe suivante | inchangée, en plus courte |

**Cette distinction n'est pas une commodité d'écriture.** La première
vérification écrite pour ce module testait la liaison *entière* et déclarait
**cinq liaisons sur onze « en faute »** sur la poche de C02. Elles ne l'étaient
pas : elle reprochait à la plongée d'entrer dans la matière qu'elle allait
couper. Un test qui interdit à une plongée de plonger ne vérifie rien.

### Vérification par un second calcul, indépendant

`hauteur_libre` raisonne par tronçon et par maximum. `touche` passe l'outil
**entier** sur la traversée et regarde ce qu'il prendrait — en réutilisant le
calcul d'enlèvement de matière, pour que les deux ne puissent pas diverger.

Sur les 7 creux du corpus qui reçoivent un parcours : **245 liaisons, 0 en
faute.**

## Mesures

| pièce | liaisons abaissées | transport | part coupante |
|---|---|---|---|
| C03 poche conique | 11/11 | 446 → **38 mm** (−91 %) | 37 → **87 %** |
| C02 poche droite | 11/11 | 566 → **160 mm** (−72 %) | 70 → **89 %** |
| C11 cavité sphérique | 20/20 | 974 → **279 mm** (−71 %) | 63 → **86 %** |
| C13 gorge torique | 2/4 | 329 → 198 mm (−40 %) | 27 → 38 % |
| C15 révolution hors axe | 39/53 | 4 899 → 3 004 mm (−39 %) | 32 → 44 % |
| C06 contre-dépouille | 22/29 | 2 366 → 1 522 mm (−36 %) | 62 → 72 % |
| C10 dôme convexe | 9/117 | 10 481 → 10 021 mm (**−4 %**) | 32 → 33 % |
| **total** | **245 liaisons, 0 en faute** | **20 061 → 15 223 mm (−24 %)** | **42 → 49 %** |

Coût : 0,2 à 2,4 s par creux, proportionnel au nombre de liaisons.

## Ce que C10 dit du chantier suivant

Le dôme ne gagne que 4 %, et c'est instructif : ses 117 liaisons vont d'une
région à l'autre **par-dessus le dôme lui-même**, qui est de la matière
protégée. Aucune hauteur plus basse n'existe — le calcul n'a rien à trouver.

Ce qui coûte là n'est pas la hauteur mais l'**ordre** : 117 liaisons pour un
seul creux veut dire beaucoup de petites régions disjointes visitées dans un
ordre quelconque. **Réordonner les passes est le levier suivant**, et ce module
ne le touche pas.

## Ce que ce module ne fait pas

- il ne change **pas l'ordre** des passes ;
- la matière qui **surplombe** la liaison la fait monter, même si l'outil
  passerait dessous. `Mᵢ` est le plus haut point de matière du couloir, sans
  regarder si la tranche du tronçon l'évite par le dessous. Sur une
  contre-dépouille, la liaison est donc plus haute que nécessaire ;
- il ne vérifie **pas** que les positions de la liaison tiennent dans les
  courses de la machine ni qu'elles évitent le plateau et le berceau. Abaisser
  une liaison ne peut que rapprocher l'outil de la pièce, donc l'éloigner des
  butées — mais ce n'est pas prouvé ici.
