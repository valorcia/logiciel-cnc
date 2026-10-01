# ADR-021 — Le corps de l'outil contre la matière

## Contexte

L'ADR-020 a posé trois vérifications sur le parcours et en a laissé une,
nommément, dans l'en-tête du fichier produit : *« Ce module ne vérifie PAS le
porte-outil contre la pièce le long du chemin. »*

C'était le dernier trou. Trois gardes existaient déjà, et aucun ne répondait à
cette question :

- `decider_creux` vérifie une **orientation**, sur quelques dizaines de points
  de bord du creux, contre la pièce finie et le brut initial ;
- le trancheur garantit qu'on ne **gouge** pas la matière protégée ;
- `gamme.verifier_le_parcours` passe toutes les poses au garde **machine** —
  berceau, joues, carters, courses.

Restait le porte-outil, la tige, le col, le nez de broche, contre la matière.

## La difficulté, et pourquoi elle n'est pas une précaution de style

**La bonne réponse dépend du moment.** Une poche se vide couche par couche. À
la couche 8, le porte-outil occupe l'endroit même où se trouvait du brut avant
la couche 1.

- Vérifier contre le **brut initial** refuserait tout usinage profond.
- Vérifier contre la **pièce finie** autoriserait un porte-outil qui traverse
  20 mm de brut encore présent.

Les deux réponses sont fausses, et **dans les deux sens**. Il n'y a pas de
raccourci : il faut suivre la matière.

## Décision

Un module `subtractive_slicer/corps.py`, posé à côté de `liaisons.py` parce
qu'il fait la même chose pour une autre question : **la matière est suivie au
fur et à mesure**, chaque passe coupante étant retirée d'une copie avant que la
suite ne soit testée.

### Qui a le droit d'être dans la matière

L'arête de coupe, évidemment. Et le **corps de goujure** : coaxial, au même
diamètre nominal, il voyage dans le canal que l'arête vient d'ouvrir — là où le
bec est passé, il passe.

C'est `ROLES_DANS_LA_COUPE`, et c'est la **même constante** que celle qui décide
ce que l'enlèvement de matière retire. En avoir deux est la façon dont elles
finissent par ne plus dire la même chose. Le balayage de vérification est lui
aussi **la même fonction** que celui de l'enlèvement, avec un filtre de rôles :
écrire une seconde géométrie d'outil pour la vérification les ferait diverger,
et celle qu'on croirait serait celle qui autorise.

### Grossier d'abord, chronologique si besoin

Un balayage groupé par tronçon de chemin répond vite, et il **majore** : il voit
plus de matière qu'il n'y en a réellement à la fin du tronçon. « Rien » signifie
donc vraiment rien, et le cas normal reste au prix du cas normal.

Quand il signale quelque chose, la réponse exacte exige une marche **pose par
pose, dans l'ordre**, qui avance la matière à chaque pas — et qui conclut très
souvent que tout va bien. C'est ce qui s'est passé au premier essai : un puits
creusé d'une seule traite était refusé par le test groupé parce qu'on
reprochait au porte-outil une matière que l'outil avait sortie quelques
millimètres plus tôt.

### Pas d'état de matière, pas de programme

`gamme_des_creux` **refuse** de construire une gamme sans état de matière. Poster
un programme dont une des quatre vérifications n'a pas eu lieu reviendrait à la
présenter comme faite. Et `verifier_le_corps` sans matière répond « **non
vérifié** », jamais « dégagé » : c'est la fausse valeur que ce projet interdit.

### Chaque creux est vérifié contre l'état INITIAL

Pas contre l'état laissé par les creux précédents. C'est le côté prudent — il y
a plus de matière au départ — et c'est volontaire : avancer l'état d'un creux à
l'autre figerait un **ordre que personne n'a encore décidé**.

## Ce que cela produit

### La grandeur qui commande le verdict

Tout tenu fixe sur le parcours réel de C02 — pièce, chemin, outil, diamètre —
sauf la **longueur sortie de pince** :

| jauge | verdict |
|---|---|
| 45, 30, 24, 22, **21 mm** | dégagé |
| **20**, 17, 14 mm | refusé — *le porte-outil*, pose 793, en (24,0 ; 33,6 ; 7,4) |

**La bascule tombe à 21/20 mm, et la poche fait 20 mm de profondeur.** Le
porte-outil entre dans la poche exactement quand la longueur sortie descend sous
sa profondeur. Le module ne répond pas « dégagé » à tout, et le seuil est là où
la physique le met.

Le logiciel répond donc, pour la première fois, à une question qu'un usineur se
pose à chaque montage : **de combien dois-je sortir cet outil ?**

### Sur le corpus

Les 23 creux, décidés puis tracés puis passés aux deux gardes :

| | |
|---|---|
| refusés dès l'orientation | 9 |
| parcours vide (marge de tranchage, cf. ADR-016) | 4 |
| **parcours réels vérifiés** | **10** |
| — dégagés par les deux gardes | **8** |
| — refusés par le garde **machine** | 2 |
| — refusés par le garde **matière** (corps de l'outil) | **0** |

15 858 poses vérifiées, **182 s** au total pour le corps de l'outil. Le filtre
grossier n'a eu à être rouvert **aucune fois** (`n_fins = 0`) : sur ces
parcours, la marche chronologique ne coûte rien. Elle compte là où l'outil sort
court — c'est le cas du tableau précédent.

### Zéro refus par le corps, et ce que cela ne prouve pas

Comme pour les joues du berceau (ADR-019), il serait malhonnête d'en conclure
que le porte-outil ne gêne jamais. **La jauge nominale du banc est de 45 mm et
les creux du corpus font au plus 20 mm de profondeur** : le corps est toujours
au-dessus de tout. Le tableau des jauges montre où cela commence à mordre, et
le module répond alors avec l'organe, l'endroit et le remède.

### Ce que le garde MACHINE a trouvé au passage

Les deux refus sont instructifs, parce qu'ils portent sur des creux dont
l'orientation **avait été approuvée** sur les points de bord :

| creux | cause | dépassement |
|---|---|---|
| C10 dôme | 208 poses hors de la course **Z** | Z = 61 mm pour une course de 60 — **1 mm** |
| C15 révolution hors axe | 16 poses hors de la course **Z** | Z = 86 à 91 mm pour une course de 60 |

**La vérification de tout le parcours attrape ce que les points de bord ne
pouvaient pas voir** : ce ne sont pas les points de contact qui sortent, c'est
le plan de dégagement des liaisons. C10 passe à 1 mm près.

À noter : `course_z_haut_mm = 60` est une cote **de plan**, pas une mesure. Ces
deux refus disent donc exactement ce qu'ils peuvent dire — que sur la machine
*dessinée*, ces deux parcours sortent en haut.

## Ce que cela ne fait toujours pas

- la vérification porte sur la matière **voxélisée**, au pas de 1 mm : un
  contact plus fin que le voxel n'est pas vu, et le voxel est dilaté de sa
  demi-diagonale, ce qui majore — donc refuse un peu trop plutôt que pas assez ;
- elle ne dit rien des **efforts de coupe**, de la flexion de l'outil, ni du
  copeau ;
- l'ordre des creux entre eux reste l'ordre reçu.
