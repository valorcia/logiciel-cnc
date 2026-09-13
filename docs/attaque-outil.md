# Le sens d'attaque de l'outil

Signalé par l'utilisateur en regardant une capture de simulation :
*« Attention au sens de l'attaque de l'outil. »* Deux défauts distincts se
cachaient derrière cette phrase. Les deux sont corrigés ; un troisième point
reste ouvert et est nommé plus bas.

## 1. Toutes les passes entraient en matière en rapide

**Mesure avant correction**, sur une ébauche du corpus (C10, deux
indexations) : **1 615 passes sur 1 615** arrivaient à la profondeur de coupe
par une descente verticale **en rapide**, s'arrêtant exactement sur le premier
point de coupe. Paliers d'approche en avance travail : **0**.

Le plus instructif est que la règle était déjà écrite dans le même fichier.
`with_approach_retract` dit, mot pour mot :

> un rapide qui finit exactement sur la surface n'a aucune marge pour une
> erreur d'origine palpée, et c'est le mouvement qui casse les outils

Elle était appliquée **une** fois — au tout premier point de l'opération — et
les liaisons entre passes, qui sont des centaines, l'ignoraient. Un principe
juste appliqué une fois sur mille n'est pas un principe, c'est une exception.

La liaison compte désormais cinq sommets au lieu de trois : sortie de matière
en avance, remontée rapide, translation rapide, descente rapide jusqu'à
`standoff` mm au-dessus du point, puis **avance travail** jusqu'au contact.
Un drapeau de rapide décrit le mouvement qui *arrive* sur son point — c'est la
convention de `with_approach_retract`, et la respecter est ce qui fait que le
dernier segment se parcourt en avance.

**Mesure après correction** : 1 615 paliers sur 1 615, 1,00 mm chacun, à
l'entrée **et** à la sortie de matière.

## 2. `can_plunge` était déclaré et lu par personne

Trouvé en écrivant le test du premier défaut. `ToolAssembly` porte depuis le
premier jalon `can_plunge` et `max_ramp_angle_deg`. Une recherche sur tout le
code source ne trouvait **aucune lecture de ces deux champs** hors du module
qui les définit.

Conséquence : le slicer produisait des plongées avec une fraise à trois dents,
qui déclare elle-même `can_plunge = False` — c'est-à-dire un mouvement que
l'outil dit ne pas pouvoir exécuter. Une donnée juste, présente et ignorée est
pire qu'une donnée absente : on croit l'avoir prise en compte.

L'entrée est maintenant une **rampe en allers-retours** sur le premier segment
de coupe, sous l'angle que l'outil déclare, quand `can_plunge` est faux.

Les allers-retours plutôt qu'une descente oblique unique : une rampe oblique
arriverait à la profondeur **après** le point de départ et laisserait derrière
elle un coin de matière que `simulate_removal` ne compte pas — le volume
enlevé rapporté deviendrait optimiste. Les allers-retours reviennent sur le
point de départ à la profondeur voulue, en ayant dégagé ce coin au passage.

**Mesure**, même poche, même couche de 3 mm :

| outil | `can_plunge` | points | rampes | angle |
|---|---|---|---|---|
| hémisphérique D6 | oui | 5 595 | — | — |
| bout droit D6, 3 dents | non | 10 044 | 4 448 | 0,48 – 2,65° |
| bout droit D6, 2 dents | oui | 5 595 | — | — |

L'angle maximal mesuré (2,65°) reste sous les 3° déclarés par l'outil. La
rampe double presque la longueur du programme — c'est le prix d'un outil qui
ne peut pas plonger, et il n'est payé que par ceux-là.

Deux cas résistent et sont **comptés plutôt que résolus en silence** : une
passe réduite à un point (aucune direction où ramper) et un segment trop court
pour ramper sous l'angle déclaré. Ces passes entrent en plongée, et le planner
**écrit le compte dans les notes de l'opération**. Une exception qu'on ne
compte pas cesse d'être une exception. Sur la poche du corpus, ce compte vaut
zéro.

## 3. Le sens de coupe alternait sans que personne ne l'ait choisi

**Mesure avant correction** : 4 634 segments de coupe dans un sens, 4 634 dans
l'autre — exactement moitié-moitié, parce que le zigzag inverse chaque rangée.
En fraisage, cela alterne l'avalant et l'opposition à chaque passe, ce qui
change l'effort, l'état de surface et le côté de la bavure.

Le défaut n'était pas l'alternance — c'est un choix défendable en ébauche —
mais que **personne ne l'ait choisie** : aucun paramètre, aucune trace, aucune
validation. Le mode est désormais nommé (`zigzag` ou `unidirectionnel`), porté
par le `SliceResult`, et **écrit dans les notes de l'opération**.

**Mesure du compromis**, même poche :

| balayage | points | rapides | sens constant | sens inverse | matière |
|---|---|---|---|---|---|
| `zigzag` | 5 595 | 1 332 | 592 | 640 | 13 808 mm³ |
| `unidirectionnel` | 6 615 | 2 382 | 1 232 | **0** | 13 808 mm³ |

Même matière enlevée, +18 % de points et **+79 % de mouvements rapides** : le
retour à vide ne peut pas se faire à la profondeur de coupe, il traverserait la
matière de la rangée suivante.

Le défaut **ne change pas** : `zigzag` reste le mode par défaut. Le changer
changerait toutes les gammes déjà validées et le temps d'usinage, en silence.

## Ce qui reste ouvert

- **L'atelier n'expose pas le choix du balayage.** C'est un paramètre de
  stratégie, et les neuf réglages de l'atelier sont ceux qui changent
  l'**accessibilité**. Les mélanger ferait croire qu'ils se valent.
- **Ni avalant ni opposition ne sont nommés comme tels.** Le mode dit dans
  quel *sens* on balaie ; dire de quel *côté* l'outil attaque demande de
  connaître le sens de rotation de la broche, qui n'est pas modélisé.
- **La vitesse d'avance de la rampe** n'est pas distincte de celle de la
  coupe. Une rampe se parcourt en général plus lentement.
