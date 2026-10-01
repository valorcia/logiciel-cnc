# ADR-022 — L'ordre des creux entre eux

## Contexte

L'ADR-018 a réordonné les passes **à l'intérieur** d'une couche. Restait la
question du dessus : dans quel ordre vider les creux d'une pièce. Trois choses
en dépendent, et elles ne sont pas du même ordre de grandeur.

1. **Les changements d'outil.** Ce kit n'a pas de changeur : le porte-outil est
   une pince ER16, et changer d'outil est une **intervention de l'opérateur** —
   on arrête, on desserre, on remonte, on rejauge.
2. **Les ré-indexations (A, C).** Faire tourner le plateau et basculer le
   berceau est un mouvement machine, et une reprise de jeu sur deux axes dont
   la fiche déclare le jeu — à zéro, parce que personne ne l'a mesuré.
3. **Le transport.** La distance entre la fin d'un creux et le début du suivant.

## Décision

### Un ordre lexicographique, pas une somme pondérée

Pondérer exigerait un **taux de change** entre « une intervention d'opérateur »,
« une rotation de plateau » et « un millimètre ». Ce taux demanderait un modèle
de temps, donc les vitesses d'avance et de rapide — qui sont, dans la fiche, des
cotes **de plan**. Habiller une estimation en optimum serait exactement ce que
ce projet refuse ailleurs.

L'ordre est donc strictement lexicographique :

1. grouper par **outil**. Pour *k* outils, le minimum de changements vaut
   *k−1*, et tout groupement l'atteint : ce terme est **exact**, pas
   heuristique ;
2. à l'intérieur d'un groupe d'outil, grouper par **orientation**. Même
   raisonnement, même exactitude ;
3. à l'intérieur d'un groupe d'orientation, raccourcir le **transport** par
   plus-proche-voisin puis 2-opt — en réutilisant les fonctions déjà écrites et
   éprouvées de `subtractive_slicer.ordre`.

**Le transport peut augmenter, et c'est assumé.** Grouper par outil peut
éloigner deux creux voisins qui n'utilisent pas le même. C'est le prix de
l'échelon supérieur ; il est **mesuré et dit** — un module qui l'appliquerait en
silence présenterait une dégradation comme une optimisation.

### L'hypothèse est dans la fiche, pas dans le code

Une cote nouvelle, `changeur_outil_automatique`, non mesurée comme les 50
autres. Elle rend visible et corrigible ce qui serait sinon enfoui : si la
machine finissait par recevoir un changeur, le raisonnement changerait, et il
faut que cela se voie à l'écran plutôt que dans un commentaire.

### Les gros outils d'abord

Les groupes d'outil sont parcourus par diamètre **décroissant** : un creux large
se vide à la grosse fraise, un creux étroit à la petite. Cela ne coûte rien,
puisque le nombre de changements ne dépend pas de l'ordre des groupes.

### Un creux ne se retourne jamais

Une passe de couche peut être parcourue dans les deux sens (ADR-018). Un creux,
non : son chemin descend couche par couche, et le prendre à l'envers remonterait
du fond vers la surface. Le 2-opt travaille ici **sans retournement**.

## Le piège, et ce qui le garde

Dès que l'ordre est décidé, la **matière évolue avec lui**. L'ADR-021 vérifiait
chaque creux contre l'état **initial**, faute d'ordre — le côté prudent. Ce n'est
plus nécessaire : chaque creux est désormais vérifié contre ce que ses
prédécesseurs ont réellement sorti.

Mais alors **un creux refusé ne doit rien avancer**. S'il avançait la matière,
tous les suivants seraient vérifiés contre un usinage qu'on ne fera pas, donc
avec **moins** de matière qu'il n'y en aura — et le porte-outil serait déclaré
dégagé là où il ne le sera pas. Rien ne crierait : la gamme serait complète, les
verdicts verts, le fichier émis.

C'est la même famille de défaut que les quinze précédentes, et c'est pourquoi un
test lui est consacré. L'implémentation est une passe avant unique : on vérifie,
et on n'avance que si on retient.

L'ordre d'émission **est** l'ordre de vérification. Vérifier dans un ordre et
émettre dans un autre annulerait le sens de la vérification.

## Ce que cela produit

### C21, une pièce écrite pour cette question

Le corpus n'avait **aucune** pièce où l'ordre des creux se pose vraiment : C05
en offre deux, du même outil ; partout ailleurs il n'y en a qu'un. Une pièce a
donc été ajoutée au générateur — six poches, deux outils, deux orientations.

| | reçu | retenu |
|---|---|---|
| ordre | 1, 2, 5, 6 | 1, 2, **6, 5** |
| changements d'outil | 1 | 1 |
| ré-indexations | 1 | 1 |
| transport | 177 mm | **132 mm** (−25 %) |

L'ordre de décomposition groupait déjà par outil et par orientation : les deux
termes supérieurs étaient donc déjà optimaux, et seul le transport bougeait.
C'est un résultat, pas une déception — un module qui aurait « amélioré » les
deux premiers aurait inventé un gain.

### Deux défauts du module, trouvés par la mesure et pas par les tests

Sur **C05** — deux creux, un seul outil, deux orientations — la première version
les intervertissait et faisait passer le transport de **36 à 61 mm**, en
annonçant *« c'est le prix du groupement par outil »*. Pour **zéro** changement
d'outil économisé.

1. Le premier sous-groupe d'orientation était choisi par `min()` sur un couple
   d'angles — c'est-à-dire sur un ordre lexicographique de nombres, donc sur
   rien. À défaut d'orientation courante, le départ naturel est l'ordre **reçu**.
2. La phrase invoquait le groupement par outil **dans tous les cas**. Une
   explication fausse est pire qu'une absence d'explication : elle empêche de
   voir le défaut qu'elle recouvre. Elle nomme maintenant le terme qui a
   réellement progressé, et se tait quand aucun ne l'a fait.

S'y ajoute la garantie au niveau de la séquence décrite plus haut. Après
correction, C05 garde son ordre reçu (36 → 36 mm) et C21 est inchangé.

### Ce que la mesure a révélé d'autre, hors de ce chantier

Deux des six poches de C21 — 12 mm de large — **annoncent un outil Ø 10 et ne
produisent aucun parcours**. Le message au lecteur est exact et donne le levier
(*« le découpage garde 1,9 mm entre l'outil et la pièce, et ce creux n'en offre
que 0,6 mm au rayon de cette fraise »*), mais le logiciel aurait pu choisir la
Ø 6 lui-même : **le choix de l'outil ne tient pas compte de la marge de
tranchage**. Deux critères pour « cet outil entre-t-il », et celui qui décide
n'est pas celui qui tranche. C'est un chantier à part, et il est noté comme tel.

### Un troisième défaut, trouvé en ouvrant l'écran

Les deux poches de 12 mm sont **déclarées usinables**, reçoivent un outil, et
n'ont aucun parcours. Un tel creux n'a ni début ni fin. L'ordonnanceur le
recevait quand même et levait un `IndexError` sur un tableau vide : **l'écran
des creux rendait une erreur 500 et ne s'ouvrait plus du tout** sur cette pièce.

Invisible aux tests — tous les creux qu'ils fabriquent ont un parcours — et
visible à la première ouverture de l'écran. Le module dit maintenant son
contrat plutôt que de planter, et les deux appelants écartent ces creux de
l'ordre **sans les faire disparaître du rapport** : un creux qu'on omet est un
creux dont l'opérateur ne sait plus rien.

## À l'écran

L'écran des creux porte désormais le **rang** de chaque creux devant ses cotes,
et une phrase qui dit ce que l'ordre économise. Les creux sans parcours n'ont
pas de rang : en donner un laisserait croire qu'ils vont se faire.

**Et un quatrième défaut, visible seulement sur la capture d'écran.** Les deux
poches sans parcours affichaient la pastille verte **« se vide »**, à côté de
lignes qui portaient un rang. C'est l'étape 3 qui avait dit oui — un outil
entre, une orientation dégage — et le découpage qui ne laissait ensuite aucune
position. Une pastille verte sur un creux qui ne sera pas usiné est exactement
la fausse valeur que ce projet interdit ; elle dit maintenant **« aucun
parcours »**.

## Ce que cela ne fait toujours pas

- un creux reste **une** opération : pas d'ébauche puis reprise séparées, alors
  que le verdict nomme déjà l'outil de reprise ;
- l'ordre ne tient pas compte de la **rigidité** du montage : vider une poche
  peut assouplir la pièce pour la suivante, et rien ne le modélise ;
- aucune contrainte de **dépendance** n'est détectée — un creux qui ne serait
  atteignable qu'après un autre serait simplement refusé, pas replanifié.
