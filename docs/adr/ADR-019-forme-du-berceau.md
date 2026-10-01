# ADR-019 — La forme du berceau : un U, et non un mur

## Contexte

Le modèle de collision de la machine portait **deux** organes : le plateau C,
un cylindre, et le berceau A, **une boîte** posée derrière la pièce —
`x ∈ [-110, 110]`, `y ∈ [-95, -80]`, `z ∈ [-70, 40]`. Une paroi pleine de
220 mm de large, sur toute la hauteur du berceau.

Le dessin de la machine réelle montre autre chose : un **U**. Deux joues de part
et d'autre de la pièce, et **deux moteurs qui dépassent latéralement**. Il n'y
a rien derrière la pièce.

Ce n'est pas une imprécision de détail. Les deux formes ne se trompent pas au
même endroit, et elles se trompent **dans les deux sens** :

- le mur arrière **barrait ce qui est libre**. Des orientations étaient
  refusées pour une matière imaginaire ;
- rien ne barrait les **côtés**, là où se trouvent réellement les joues et les
  carters. Des poses où l'outil entre dans une joue étaient déclarées dégagées.

Le second défaut est le grave. Le projet interdit de présenter comme acquis ce
qui ne l'est pas ; déclarer dégagée une pose qui ne l'est pas est la même faute,
du côté le plus coûteux.

## Décision

Décrire le berceau tel qu'il est, **à partir de la fiche machine**, par cinq
organes au lieu de deux :

| organe | repère | forme |
|---|---|---|
| plateau C | `table_C` | cylindre |
| joue gauche / droite | `cradle_A` | boîte |
| moteur A gauche / droite | `machine` | boîte |

### Le repère n'est pas un détail d'écriture

Les joues tournent avec le berceau : repère `cradle_A`. **Les carters de moteur
ne tournent pas** — c'est le rotor qui tourne, le stator est boulonné sur le
bâti. Ils vont donc dans le repère fixe `machine`.

Placer un carter dans `cradle_A` l'aurait fait basculer avec la pièce, donc
**s'écarter tout seul des orientations où il gêne le plus**. Une collision qui
s'efface précisément quand on en a besoin : c'est la famille de défaut que ce
projet rencontre depuis le début, une grandeur dominée par une autre et lue
comme si elle mesurait ce qu'on voulait.

### Une boîte pour le carter, pas un cylindre

Première écriture de cette décision : un **cylindre** de diamètre
`moteur_a_diametre_mm`, justifié par « un cylindre circonscrit au carré majore,
donc l'erreur est du côté prudent ».

**C'est faux, et dans le mauvais sens.** Un cylindre de 42 mm de diamètre est
*inscrit* dans un carré de 42 mm de côté : ce sont les quatre coins du carter
qui dépassent, de 8,7 mm sur la diagonale d'un NEMA 17. La phrase annonçait la
prudence et le code faisait l'inverse.

Le carter est donc une **boîte** du côté déclaré, faces parallèles à la table.
Exact pour un carter carré monté droit — et un NEMA se boulonne par quatre trous
en carré, donc à 90° près, toutes les positions possibles donnent des faces
parallèles à Y et Z.

### Deux hypothèses nommées, aucune mesurée

Elles ne sont pas cachées dans le code : elles sont écrites dans la docstring et
vérifiables **à l'œil** le jour où la machine existe.

1. Les moteurs sont **coaxiaux** à l'axe A (entraînement direct). Une courroie
   les déporterait, et il faudrait deux cotes de plus pour dire où.
2. Le carter carré est monté **droit** (§ ci-dessus).

Les quatre cotes nouvelles entrent dans la fiche avec la provenance `PLAN`, comme
les 46 autres. Taper un nombre ne le rend pas mesuré ; la fiche passe de 46 à
**50 cotes**, et aucune n'est mesurée aujourd'hui.

## Conséquences

### Ce que cela change aux verdicts

Les 23 creux du corpus, décidés deux fois — une fois avec le mur, une fois
avec le U, tout le reste identique. **Deux creux changent de verdict, et les
deux passent de « refusé » à « usinable »** :

| creux | avant | après |
|---|---|---|
| C05 ailettes #2 | refusé — 11 des 51 points bloqués par un organe | Ø 10 mm à **A = −90°, C = 0°** |
| C05 ailettes #3 | refusé — 21 des 52 points bloqués par un organe | Ø 10 mm à **A = −90°, C = −180°** |

C'étaient les deux refus que le mur imaginaire provoquait : à A = −90° la pièce
est couchée, et l'ancienne paroi se retrouvait exactement sur le chemin de
l'outil — une paroi qui n'existe pas. Le corpus passe donc de **12 à 14 creux
usinables sur 23**.

### Ce que la mesure ne dit PAS

**Aucun creux n'est refusé par les nouvelles joues ni par les carters.** Il
serait malhonnête d'en conclure qu'ils ne gênent jamais : cela veut seulement
dire que **le corpus ne va jamais là**. Mesuré sur les 20 bruts : le plus étendu
(C04) atteint **72 mm** du centre du plateau, quand la face intérieure d'une
joue est à **95 mm** et le carter au-delà de **110 mm**. Il reste 23 mm d'air
entre le bord du brut le plus large et la joue la plus proche ; l'outil n'a
jamais eu l'occasion de les rencontrer.

Les joues ne commenceront à refuser que sur une pièce large, ou excentrée sur le
plateau — c'est-à-dire exactement le cas où l'ancien modèle était muet. Le gain
de sécurité est donc réel mais **non démontré par ce corpus** ; il est démontré
pose par pose par les tests du garde de collision, qui interrogent les joues là
où elles sont.

### Cette mesure a dû être refaite, et elle n'a pas bougé

La première exécution de ce tableau a été obtenue avec **la moitié des organes
invisibles** : le cache de nuages du garde vectorisé était indexé par le nom du
repère, si bien que la joue droite et un carter n'étaient jamais testés. Le
défaut est raconté dans l'ADR-020, qui l'a découvert et corrigé.

Le tableau ci-dessus est celui de la mesure **refaite après correction**. Il est
identique au premier, verdict par verdict et angle par angle — et cela
*confirme* l'explication plutôt que de l'affaiblir : si le corpus n'approche
jamais les joues, voir une joue de plus ou de moins ne pouvait rien changer. Le
premier chiffre était juste par accident ; celui-ci l'est par construction.

### Ce que cela ne change pas

La machine réelle n'est toujours pas mesurée. Ces cotes sont des cotes de
plan : elles rendent le modèle de la **bonne forme**, pas des bonnes dimensions.
Un berceau de la bonne forme et des mauvaises cotes refuse et accepte au mauvais
endroit, simplement de façon cohérente — et c'est corrigible par les neuf
mesures au pied à coulisse dont les organes dépendent, ce que l'ancienne forme
n'était pas.

### Ce qui reste à faire

- les **bras et les colonnes du delta** ne sont toujours aucun organe de
  collision : l'outil peut, dans le modèle, traverser un bras ;
- la **broche** n'est présente que par son enveloppe outil ;
- la jonction joue/moteur est modélisée bout à bout, sans le palier qui les
  relie réellement.
