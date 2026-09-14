# ADR-012 — La machine est une DELTA linéaire XYZ + table A/C

## Contexte

Le projet a été construit sur une cinématique **XYZAC table/table** : trois axes
linéaires orthogonaux, un berceau A et un plateau C portant la pièce. La machine
réelle, dont la conception m'a été montrée, est différente :

- trois colonnes verticales à 120°, un moteur et un chariot sur chacune ;
- six bras à rotules, par paires (parallélogrammes), joignant les chariots à une
  plateforme centrale qui porte la broche ;
- **la plateforme ne tourne pas** : les parallélogrammes la maintiennent
  parallèle à la base. Elle ne fait que **translater** → X, Y, Z ;
- les deux rotatifs **A et C sont sur la table**, sous la broche.

Soit : **XYZ delta + AC**.

## Ce qui survit sans changer une ligne

La structure « trois translations + table A/C » est *exactement* celle que ce
projet modélise. Tout ce qui touche à l'**orientation** reste valable :

- `tool_axis_in_part(A, C)` et `rotation_machine_from_part` ;
- les six montages canoniques et le dépistage ;
- le solveur d'accessibilité, le trancheur, le bridage, la finition ;
- tout le raisonnement 3+2, et le partage entre ce qui tient au montage, à
  l'outil et au dessin.

C'est la moitié du logiciel, et c'est la plus difficile.

## Ce qui tombe

**1. Les courses cessent d'être un pavé.** Les butées portent sur les positions
de chariots `q_i`, pas sur X, Y, Z :

    q_i = z + sqrt(L² − a_i² − b_i²),  a_i = (R−r)cos θ_i − x,  b_i = (R−r)sin θ_i − y

La borne haute `q_i ≤ q_max` s'écrit `z ≤ q_max − s_i(x,y)` avec `s_i` concave,
donc le majorant est **convexe** : le volume n'est pas convexe. `travel.py`
reposait explicitement sur « le domaine est une boîte, donc convexe, donc tester
les sommets suffit ». **Cet argument est faux ici** — et un contre-exemple est
exhibé par un test, faute de quoi rien ne prouverait que la correction servait à
quelque chose.

**2. L'avance rapide** `min_i(V_i/|d_i|)` supposait trois axes indépendants. La
vitesse d'un chariot est une fonction non linéaire de la position *et* de la
direction.

**3. Les organes machine** : plateau C et berceau A ne décrivent plus le
volume à éviter. Ce sont désormais trois colonnes, un anneau supérieur, et
surtout **les bras, qui balaient un volume important**.

## Décision

Un module `machine_model.delta` porte la cinématique parallèle, et
`MachineKinematics.delta` la rend optionnelle : `None` = portique ou
table/table, un `DeltaLineaire` = trois chariots. Les modules qui supposaient un
pavé **demandent** désormais (`machine.lineaire_parallele`) au lieu de supposer.

### L'exactitude est conservée, et elle se démontre

Le long d'un **segment droit** :

- `a_i(t)² + b_i(t)²` est une parabole **convexe** en `t` → son maximum est à
  une extrémité : la portée des bras est exactement vérifiée par les deux bouts ;
- `q_i(t) = z(t) + sqrt(L² − a² − b²)` est **concave** (affine + racine d'une
  concave positive) → son **minimum** est à une extrémité : la butée basse aussi ;
- son **maximum** peut être intérieur, mais une concave n'en a qu'un, et il
  annule la dérivée : équation du second degré, résolue en forme close.

**Aucun échantillonnage, aucune réserve.** Mesuré : 2 000 segments tirés au
hasard, comparés à un échantillonnage à 401 points — **0 faux positif, 0
désaccord**. Un faux positif serait une machine qui part en butée.

### Le remède n'a plus de forme close

Le décalage qui ramène la trajectoire dans le volume ne se lit plus sur une
différence de bornes. Il est donc **cherché puis vérifié** : chaque candidat est
rejoué sur l'ensemble des positions, et rien n'est proposé qui n'ait passé ce
test. C'est plus sûr que la forme close, qui elle n'était jamais rejouée.

La recherche est volontairement pauvre — six directions d'axe, dichotomie sur
l'amplitude. Un volume non convexe admettrait des décalages exotiques qu'aucun
opérateur ne saurait réaliser sur ses cales.

### Deux causes de refus, et elles ne se corrigent pas pareil

« Hors de **portée** des bras » et « aucun décalage essayé ne suffit » sont
distincts et nommés. Les déduire d'un champ cartésien produisait la phrase
*« il manque 0 mm de plus que toute la course X »* — sur une machine qui n'a pas
de course X.

## Ce qui reste ouvert

- **Les cotes du châssis** : R, r, L, la course des chariots. Les valeurs
  actuelles sont **PROVISOIRES et déclarées comme telles**, au même titre que
  celles de `default_xyzac_kit`. Elles décident du volume de travail, donc de ce
  que la machine peut usiner.
- **Les organes en collision** : colonnes, anneau, et le volume balayé par les
  bras. Rien n'est modélisé pour l'instant — donc rien n'est prétendu.
- **La raideur**, qui varie dans le volume et chute près des bords et des
  configurations de bras tendus. Sur une machine d'usinage, où l'effort de coupe
  pousse la plateforme, c'est une question de premier ordre. Elle demande des
  mesures sur la machine assemblée, pas une formule : elle n'est donc pas
  traitée plutôt qu'estimée.
- **La couche de pilotage** : LinuxCNC fournit `lineardeltakins`. C'est là que
  la cinématique inverse doit être *exécutée* ; celle de ce module sert à
  décider, pas à commander.
