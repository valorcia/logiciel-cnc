# ADR-024 — La configuration LinuxCNC décrivait une autre machine

## Contexte

`linuxcnc_gateway.config` écrit `KINEMATICS = xyzac-trt-kins`. Son commentaire
disait, depuis le jalon M9 :

> *xyzac-trt-kins, qui est exactement la cinématique de cette machine —
> table/table avec berceau A et plateau C. C'est une chance, et cela évite
> d'écrire un module C.*

C'était vrai quand ce commentaire a été écrit. **L'ADR-012 a fait de la partie
linéaire une delta**, et la phrase est restée.

Ce module de LinuxCNC pose que les articulations 0, 1 et 2 **sont** X, Y et Z.
Sur un portique, c'est juste. Sur la delta de ce kit, les articulations 0, 1 et
2 sont les trois **chariots** : leur course est celle des colonnes — 0 à
300 mm, les trois identiques — et non les demi-courses cartésiennes, qui
décrivent un volume atteignable qui n'est même pas un pavé.

La configuration générée pour la machine de la fiche déclarait pourtant :

    [JOINT_0]  MIN_LIMIT = -150.5   MAX_LIMIT = 150.5
    [JOINT_1]  MIN_LIMIT = -120.5   MAX_LIMIT = 120.5
    [JOINT_2]  MIN_LIMIT = -120.5   MAX_LIMIT =  60.5

Trois courses différentes pour trois colonnes identiques, et aucun mot nulle
part — ni dans `to_verify`, ni dans `provisional`.

**Le fichier aurait démarré.** Il aurait pris son origine, et commandé les
chariots comme s'ils étaient des axes cartésiens : chaque déplacement faux,
aucune erreur signalée. C'est le pire mode d'échec de tout ce projet, et c'est
exactement celui que le reste du code passe son temps à éviter.

## Décision

### 1. Refuser, totalement

`build_config` **lève** quand la machine est une delta. Pas un avertissement
dans une liste : un fichier qui décrit une autre machine que celle qu'on a est
pire qu'une absence de fichier, parce qu'il démarre.

Le refus donne les vraies butées de chariot, pour que l'écart se voie, et dit
où est la réponse plutôt que de laisser sans suite.

Une XYZAC **à portique** reste exactement la machine de `xyzac-trt-kins` : sa
configuration continue de se générer sans un mot de plus, et un test l'exige.

### 2. Établir la composition, et la vérifier

`kinematics_solver.delta_ac` est la **référence numérique** de ce que le module
C devra calculer. Il n'exécute rien.

    (x, y, z, A, C)  --[inverse TRT]-->  (xm, ym, zm, A, C)
                     --[inverse delta]-> (q0, q1, q2, A, C)

Les deux étages se composent **sans terme croisé**, parce que la plateforme de
la delta translate sans tourner (paires de bras en parallélogramme). C'est la
seule raison pour laquelle le futur module C est modeste — il n'aurait qu'à
appeler l'inverse TRT existant puis la formule des chariots — et elle est donc
**vérifiée plutôt que supposée** : un test compare la composition complète aux
deux étages pris séparément.

### 3. Le retour, qui n'existait pas

`DeltaLineaire` donne les chariots depuis la plateforme ; l'inverse n'existait
nulle part, parce qu'elle n'en avait pas besoin pour **décider**. Il est résolu
ici par intersection de trois sphères, et **c'est l'aller-retour qui le
vérifie** : 400 poses tirées dans le volume, écart maximal **8,4 × 10⁻¹⁴ mm**.

Trois sphères se coupent en deux points. La racine retenue est celle où les
bras **descendent** — le même choix de signe que `DeltaLineaire.chariots`, et il
doit l'être, sinon l'aller-retour ne se refermerait pas. Un test le nomme au
lieu de le laisser implicite.

## Ce qui a été vérifié contre LinuxCNC lui-même

L'étage TRT de ce module est une transcription littérale de
`xyzacKinematicsInverse`. Sa fidélité **n'est pas supposée** :
`tools/verify_kinematics_linuxcnc.py --etage source` compile `trtfuncs.c` de
LinuxCNC 2.9 avec quatre bouchons HAL et appelle sa fonction.

> **56 poses, écart maximal 7,1 × 10⁻¹⁵ mm.**

Cet étage ne tournait plus : il cherchait ses en-têtes dans `include/` et
`src/`, que **le build de LinuxCNC crée**. Autrement dit, la vérification la
plus importante du lot ne pouvait se faire que là où elle était déjà faite. Les
répertoires réels ont été ajoutés (`src/emc/motion`, `src/emc/tp`,
`src/libnml/posemath`) et l'étage tourne désormais contre un simple
`git clone --branch 2.9`.

## Ce que cela n'établit pas

- **Le module C n'existe pas.** Rien n'est généré pour la delta, et c'est le
  propos de cette décision ;
- l'étage 3 — LinuxCNC lancé, mis en marche, interrogé en MDI — demande
  LinuxCNC installé ; il n'a pas été rejoué ici ;
- le **signe** des axes sur la machine réelle, qu'aucun calcul n'établit : il
  faut commander un déplacement et regarder de quel côté la pièce part ;
- la **raideur** de la delta et les singularités de bras, qui demandent des
  mesures sur la machine assemblée.
