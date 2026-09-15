# ADR-013 — La matière à enlever, considérée comme une pièce

## Contexte

Jusqu'ici le logiciel raisonnait sur les **surfaces de la pièce finie** : une
liste de faces, un verdict par face, une orientation par face. C'est le point de
vue du **dessin**. Ce n'est pas celui de l'usinage.

Un usineur ne regarde pas une face : il regarde un **creux**, et se demande
« qu'est-ce que je sors de là, et avec quoi ? ». La matière à enlever est un
objet — une forme, un volume, un goulot — bref une pièce en négatif.

Conséquence directe : **l'outil cesse d'être un réglage global pour devenir une
réponse**, et une réponse par volume. Une poche large se vide à la fraise de
10 mm ; le congé au fond de la même poche demande 3 mm. Ce ne sont pas deux
réglages concurrents, ce sont deux opérations sur le même volume.

## Décision

`feature_engine.volumes` traite la matière enlevable comme un ensemble de
volumes, et essaie **chaque outil sur chacun**.

### Ce qu'un outil peut enlever a une réponse exacte

Ce n'est pas « le plus gros qui rentre quelque part ». Un outil de rayon `r`
n'atteint que l'**ouverture morphologique** du volume par une boule de rayon
`r` — ce que la boule balaie quand on la promène partout où elle tient. Elle se
calcule avec deux transformées de distance, sans construire d'élément
structurant : le cœur (`d ≥ r`), puis les points à portée d'un cœur.

### Deux corrections que la mesure a imposées

**1. Un outil plus fin que le pas de grille rendait 100 %.** À un pas de 1 mm,
un rayon de 0,75 mm donnait « 100 % » sur les quatre pièces essayées. Ce n'était
pas une propriété des pièces : tout voxel intérieur est à une distance ≥ 1 du
fond, donc tout rayon sous 1 voxel a son cœur partout. Un tel outil est
**indiscernable d'un outil infiniment fin** ; le module le dit (`discriminant =
False`) plutôt que de rendre la réponse la plus flatteuse possible.

**2. L'ouverture sortait du volume** — trouvé par le test qui vérifie
l'inclusion. La transformée de distance mesure vers le **centre** du voxel de
fond, pas vers la frontière : un demi-voxel d'écart. Il est désormais retiré du
budget (`d ≥ r + 0,5`) et l'ouverture est intersectée avec le volume, puisqu'une
ouverture est par définition contenue dans ce qu'on ouvre.

Cette seconde correction n'a pas seulement rétabli une propriété : elle a rendu
la comparaison **informative**. Sur `C05_ailettes_rapprochees` :

| outil | avant | après |
|---|---|---|
| Ø 10 mm | 89 % | **63 %** |
| Ø 6 mm | 90 % | **86 %** |
| Ø 3 mm | 90 % | **90 %** |

Avant, les trois outils donnaient le même chiffre — c'est-à-dire aucune
information. Après, un Ø 10 laisse 37 % à reprendre et un Ø 6 en laisse 14 %.
C'est exactement la question posée.

### Le sens de l'erreur est favorable, et il est énoncé

La marge du demi-voxel rétrécit le cœur, donc l'ouverture : un outil se voit
attribuer **moins** de matière qu'il n'en sortirait.

- « cet outil enlève au moins ce volume » est fiable ;
- « cet outil n'atteint pas ce coin » peut être pessimiste d'un demi-voxel.

On ne promet pas à un outil une matière qu'il ne sortirait pas.

### 6-connexité, et pas 26

Deux cavités qui ne se touchent que par une **arête** de voxel ne communiquent
pas : aucun outil ne passe par une arête. Les relier ferait croire à une seule
poche, donc à un seul outil pour les deux.

## Ce que ce module ne fait pas

**Il ne connaît ni l'orientation ni la machine.** Une ouverture dit qu'un outil
*tient* dans le creux ; elle ne dit pas qu'il peut y *arriver* avec sa tige, son
porte-outil et son nez de broche, depuis un couple (A, C) réalisable. C'est le
travail du solveur d'accessibilité, et il vient **après** : sur un volume où
aucun outil n'entre, il n'y a rien à orienter.

L'enchaînement visé est donc : **quels volumes ? quel outil dans chacun ? depuis
quelle orientation ?** — et chaque étape peut refuser pour sa propre raison.

**Une composante connexe n'est pas une poche.** Sur une pièce prismatique, le
brut enveloppe la pièce d'une peau continue (2 mm de marge par face) qui relie
toutes les cavités en un seul bloc. Mesuré sur C02 : un seul volume de
47 669 mm³, où la peau domine le compte. Deux façons de s'en sortir, dont la
première est disponible :

1. passer un `masque` — typiquement `material.reachable_from(d)` — pour ne
   décomposer que ce qu'une direction voit. De +X, la poche C02 ne montre qu'une
   peau où la plus grosse boule fait Ø 4 mm et où une fraise de Ø 10 prend 0 % ;
2. **séparer la peau des cavités**, ce qui reste à faire.

**Il n'y a pas de profondeur.** Une propriété `profondeur_mm` rendait la plus
grande des trois étendues, et annonçait « 64 mm de profondeur » pour une poche
profonde de 29. La profondeur n'existe pas sans direction d'attaque : le module
rend les trois cotes et laisse la profondeur à qui connaît l'orientation.
