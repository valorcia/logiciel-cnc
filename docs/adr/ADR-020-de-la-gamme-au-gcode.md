# ADR-020 — De la gamme au G-code : ce qu'il a fallu vérifier d'abord

## Contexte

La chaîne existait **aux deux bouts**, et nulle part au milieu.

- `strategy_planner/creux.py` décide, pour chaque creux, quel outil et depuis
  quelle orientation, et produit un `ParcoursCreux` : des positions de bec et un
  couple (A, C) fixe.
- `postprocessor_linuxcnc/emit.py` écrit du G-code LinuxCNC compensé, derrière
  les portes de sécurité, contre une géométrie **mesurée**, et refuse plutôt que
  d'inventer une avance.

Entre les deux, rien. Et « rien » n'était pas un trou de plomberie : c'étaient
**trois questions auxquelles personne ne répondait**.

## Décision

Un module `strategy_planner/gamme.py` qui convertit, et qui **refuse** plutôt
que de convertir quand une des trois réponses manque.

### 1. Le parcours entier est vérifié, et pas seulement ses points de bord

`decider_creux` vérifie l'orientation sur quelques dizaines de **points de
bord** du creux. Un parcours en compte des milliers et descend couche par
couche jusqu'au fond. Rien ne garantissait que le nez de broche dégage encore au
dernier niveau, ni qu'une liaison abaissée reste dans les courses.

`verifier_le_parcours` passe le garde machine sur **toutes** les poses, à (A, C)
fixe, et distingue deux causes qui n'ont pas le même levier : **hors course**
(rapprocher la pièce du centre) et **collision d'organe** (raccourcir la
longueur sortie). Les confondre enverrait l'utilisateur réparer ce qui n'est pas
cassé.

Ce qui reste **non vérifié**, et qui est écrit dans le code comme dans
l'en-tête du fichier : le porte-outil contre la **pièce** le long du chemin. La
distinction est réelle — une fraise est censée entrer dans la matière qu'elle
enlève — et la trancher demande l'état de matière à chaque instant.

### 2. La posture approuvée traverse la chaîne au lieu d'être redevinée

C'est la **quinzième occurrence** de la même famille de défaut.

`ik_best(d)` répond à « quel couple (A, C) donne cet axe outil ». Ce n'est pas
la question. La question est « quel couple le contrôle de collision a-t-il
approuvé ». Les deux branches de l'inverse, (a, c) et (−a, c + 180), donnent le
**même axe outil dans le repère pièce** en posant la pièce de deux façons
différentes dans le berceau — donc avec **deux verdicts de collision
différents**, puisque les joues et les carters ne sont pas au même endroit par
rapport à elle.

Sur le kit, les butées A = [−120°, +30°] n'en laissent souvent qu'une, et les
deux réponses coïncident : le défaut est **invisible tant que la machine a ces
butées-là**. L'opération porte donc désormais son couple (`ac_impose`), et
l'émetteur le **relit** : la cinématique directe doit redonner l'axe que la
trajectoire demande, et le couple doit être dans les butées. Un couple imposé
faux serait pire que pas de couple du tout.

### 3. Une descente n'est jamais un rapide

**Défaut vu sur le tout premier fichier produit, et pas avant.**

`abaisser_les_liaisons` remplace chaque liaison par quatre sommets : monter,
traverser, redescendre. Ce qui est démontré dégagé est le **couloir
horizontal** — la hauteur retenue dégage l'outil au-dessus de toute la matière
du couloir. La descente finale, elle, rejoint le début de la passe suivante,
c'est-à-dire une position où il y a de la matière **par définition**, puisque
c'est là qu'on va couper.

Le fichier la portait en `G0`. L'émetteur refuse déjà exactement cela pour le
premier point d'une opération, avec cette phrase : *« le défaut prudent est
l'avance travail partout »*. La même règle vaut ici, et pour la même raison.

La **montée** reste en rapide : remonter le long de l'axe outil depuis une
position que l'outil occupait déjà ne rencontre que le vide qu'il vient de
laisser. Sur C02 : **11 descentes** ramenées en avance travail, 33 rapides
conservés sur 859 poses.

### 4. L'en-tête ne signe plus une vérification qu'il n'a pas faite

Il annonçait : *« Approches, liaisons et dégagements portés par la trajectoire
et validés comme le reste du mouvement. »* C'était vrai du temps où les seules
trajectoires venaient d'un module qui validait tout. C'est devenu faux le jour
où une gamme par creux est arrivée. Il dit maintenant qu'il **n'est pas** celui
qui vérifie, et renvoie à ce que chaque opération déclare d'elle-même.

## Le défaut que ce chantier a découvert ailleurs

En écrivant le test « une pose dans une joue doit être refusée », le test a
**échoué alors que le refus était attendu**. Le garde de collision a deux
chemins pour la même question :

- `check_pose` concatène tous les organes dans un seul nuage ;
- `check_many` les teste organe par organe, chacun dans son repère — c'est ce
  qui rend le solveur d'accessibilité tenable.

Le cache des nuages de `check_many` était indexé par **le nom du repère**. Tant
que chaque repère ne portait qu'un organe, la clé était fidèle. L'ADR-019 a
remplacé le berceau par **deux joues** dans `cradle_A` et **deux carters** dans
`machine` : à partir du deuxième, le cache rendait le nuage du **premier**.

**La joue droite et un carter n'étaient jamais testés** — et c'est le chemin
vectorisé, celui qui décide, qui les ignorait. Chaque chemin restait cohérent
avec lui-même, et aucun test ne les confrontait : c'est exactement de là que
venait le silence. Un test les compare désormais sur les mêmes poses, à trois
valeurs de A, sur des poses choisies pour toucher **chaque** organe, y compris
les seconds de leur repère.

Conséquence directe : **la mesure corpus de l'ADR-019 a été refaite**, celle
d'origine ayant été obtenue avec la moitié des organes invisibles.

## Ce que cela produit

Sur **C02** (poche droite 30 × 30 × 20 mm), la chaîne complète lancée pour de
bon — pièce STEP, décomposition en creux, décision, parcours, vérification,
recette, portes de sécurité, calibration **simulée sur le jumeau**, émission :

| | |
|---|---|
| creux usinables | 1 sur 1 |
| poses émises | **859**, toutes dégagées à A = 0°, C = 0° |
| fichier | 893 lignes, `out/C02_creux.ngc` |
| rapides / avance travail | 33 `G0`, 826 `G1` |
| descentes freinées | 11 |
| aller-retour sur la géométrie **mesurée** | **0,066 µm** (quantification du format : 0,1 µm) |
| aller-retour sur la **vraie** machine | **3,1 µm**, pour un budget annoncé de **51,5 µm** → majoré |

L'aller-retour n'est pas une vérification de l'émetteur contre son propre
calcul : le fichier est **relu**, et la cinématique **réelle** est rejouée sur
les valeurs relues, puis comparée au point de contact demandé. Deux fois : sur
la géométrie mesurée, où il ne doit rester que la quantification du format ; et
sur la machine vraie, où le résidu de calibration doit tenir **sous** le budget
annoncé — sinon le budget n'annonce rien.

La recette, elle, parle d'elle-même et c'est voulu : elle écrit dans l'en-tête
que la vitesse de coupe obtenue est de 188 m/min contre 120 visés, parce que la
broche ne descend pas sous 6 000 tr/min, et qu'il faudrait donc un outil **plus
petit**. Un module qui aurait tu cet écart aurait livré un fichier qui brûle
l'arête.

## Ce que cela n'autorise toujours pas

Rien n'a changé du verrou. `linuxcnc_gateway` reste verrouillé, et le fichier le
dit à son lecteur. Poster un programme exige les portes franchies et une
géométrie **mesurée** ; l'envoyer exige en plus une machine qualifiée, c'est-à-
dire la pièce d'épreuve usinée **puis mesurée sur un moyen indépendant**. La
calibration utilisée ici est **simulée sur le jumeau** : elle prouve que la
chaîne de calcul se referme sur elle-même, et rien sur une machine qui n'existe
pas.
