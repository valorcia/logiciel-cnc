# ADR-009 — Jalon M9 : la frontière LinuxCNC

- **Statut** : Accepté (jalon M9)
- **Date** : 2026-09-12
- **Contexte** : complète ADR-001 à ADR-008.

---

## 1. Ce que M9 apporte, et ce qu'il ne peut pas vérifier

**La limite d'abord, parce qu'elle change ce qu'on a le droit d'affirmer.**

Ce jalon a d'abord été livré en affirmant : « LinuxCNC n'est pas installable
dans l'environnement de développement — absent des dépôts Ubuntu, son propre
dépôt inaccessible depuis le mandataire réseau — donc aucun fichier produit par
ce jalon n'a été chargé par LinuxCNC ». **Les deux constats étaient exacts et la
conclusion était fausse.** Le 403 portait sur `ppa.launchpadcontent.net`,
c'est-à-dire sur les *paquets binaires* ; le dépôt source sur GitHub répond, et
l'archive Ubuntu principale aussi. LinuxCNC 2.9 a donc été **compilé depuis sa
source** en mode `uspace`, et la configuration lui a été donnée à charger.

Elle portait **cinq défauts**, dont deux silencieux. Ils sont consignés dans
[la note de validation](../validation-linuxcnc.md) avec la procédure complète,
et chacun est désormais tenu par un test qui ne demande pas LinuxCNC.

Après correction, la configuration démarre : cinématique instanciée, cinq
articulations, `task: 1063 cycles, 0 latency excursions`. Ce qui reste
non prouvé est énuméré au §3, et `verification_command()` donne toujours la
commande à passer sur la machine de l'utilisateur — car c'est sa machine, pas
la configuration, qui décide du signe des offsets.

Ce que M9 apporte malgré cela :

- la configuration LinuxCNC **dérivée** du modèle machine et du dossier de
  calibration, au lieu d'être saisie à la main ;
- la remise d'un programme sous conditions, qui reprend une à une les règles
  posées au premier jalon ;
- et une décision : **aucun démarrage de cycle depuis ce logiciel.**

| Limite M8 | Traitement M9 | État |
|---|---|---|
| Aucune configuration LinuxCNC | générée depuis le modèle et la calibration | **levée**, non validée par LinuxCNC |
| `linuxcnc_gateway` ébauche | dépôt de programme sous conditions | **levée** |
| Machine non construite ni qualifiée | inchangé | **ouverte** |
| Démarrage de cycle | **refusé par conception** | fermée volontairement |

---

## 2. Décisions

### D77 — La configuration est dérivée, jamais saisie

Les courses, les vitesses, les jeux et surtout **les positions des pivots A et
C** existent déjà dans `MachineKinematics` et dans le dossier de calibration.
Les retaper dans un INI, ce serait garantir qu'un jour les deux divergeront —
et sur une cinématique table/table, une erreur de pivot se propage directement
à la pièce.

L'en-tête du fichier porte donc « NE PAS ÉDITER À LA MAIN », avec son motif :
une modification manuelle serait perdue à la régénération, et surtout elle
désynchroniserait la configuration du modèle contre lequel les collisions sont
vérifiées.

C'est aussi le **lien concret** qui donne une raison d'être à M7 : sans lui,
la calibration mesurerait des pivots que personne n'emploie.

### D78 — `xyzac-trt-kins`, et pas `trivkins`

LinuxCNC fournit `xyzac-trt-kins`, qui est exactement la cinématique de cette
machine — table/table avec berceau A portant un plateau C. C'est une chance :
elle évite d'écrire et de maintenir un module de cinématique en C.

Employer `trivkins` ferait **ignorer les pivots**, donc produirait une pièce
fausse sur toute pose inclinée — sans qu'aucune erreur ne soit signalée. Un
test vérifie que `trivkins` n'apparaît nulle part.

### D79 — Trois degrés de confiance, et ils sont écrits

La configuration n'est pas d'un seul bloc quant à ce qu'on peut en affirmer :

| partie | confiance |
|---|---|
| structure INI, courses, vitesses, accélérations | reprises du modèle ; forme stable de longue date dans LinuxCNC |
| module de cinématique | fourni par LinuxCNC pour ce type de machine |
| **noms des broches HAL du module** | **non garantis** : ils varient selon la version |

Les noms de broches sont donc écrits dans un bloc isolé, précédé de la commande
qui les vérifie (`halcmd show pin xyzac`). Et le mode d'échec est le bon : **un
nom erroné fait échouer le démarrage de LinuxCNC**, bruyamment, sans mouvement.

### D80 — Le point dangereux est le signe, et il ne provoque aucun échec

Un offset de bon nom et de **mauvais signe** ne fait échouer aucun démarrage :
il fait usiner faux. C'est donc lui, et non les noms de broches, que la
configuration désigne comme le point à vérifier avant tout mouvement.

Et il ne peut être établi que par l'étape `AXIS_DIRECTION` de
`assembly_calibration` — commander un déplacement et **regarder** de quel côté
la pièce part. Cette étape est `HARDWARE_ONLY` depuis M7, et ce jalon confirme
pourquoi : aucun calcul ne remplace ce regard.

### D81 — Prise d'origine et table d'outils laissées vides, avec leur motif

`HOME_OFFSET` et `HOME_SEARCH_VEL` ne sont pas renseignés : ils dépendent du
câblage réel des capteurs, que seule l'étape `WIRING_TEST` peut établir. Les
renseigner au hasard ferait partir un axe dans la mauvaise direction à la
première prise d'origine — un mouvement non commandé vers une butée.

La table d'outils est vide pour la même raison : les longueurs doivent être
**mesurées** (`probing_service`), jamais saisies. Une jauge fausse décale toute
la gamme en Z, et c'est l'erreur la plus courante et la plus coûteuse.

Dans les deux cas le fichier dit pourquoi il est vide. Un fichier vide sans
explication se fait remplir par le premier qui passe.

### D82 — Ce qui traverse la frontière est un fichier, pas un appel de fonction

Deux contraintes indépendantes imposent la même architecture, ce qui est un bon
signe :

- **sécurité** (ADR-001 / D9) : un seul point de passage vers le mouvement
  réel, auditable, et aucun autre module n'ouvre de port machine ;
- **licence** (ADR-001 / D10) : LinuxCNC est GPLv2. Un `import linuxcnc` dans
  notre processus poserait la question de l'œuvre dérivée pour **toute**
  l'application.

Un test vérifie sur l'arbre syntaxique qu'aucun module du projet n'importe
`linuxcnc`, `hal` ni `emc`.

### D83 — Aucun démarrage de cycle : décision, pas manque

`start_cycle` lève, et ne sera pas implémenté ici.

Déposer un fichier dans le répertoire que LinuxCNC lit, puis laisser
l'opérateur l'ouvrir et appuyer sur départ cycle, garde un humain dans la
boucle **au dernier moment** — celui où l'on regarde la machine avant qu'elle
bouge. Un démarrage à distance supprime précisément ce regard, pour gagner un
geste. Sur une machine 5 axes en kit dont le bridage vient d'être refait à la
main, ce regard est la dernière barrière qui ne dépende d'aucun calcul.

La règle du projet dit que l'IA ne pilote jamais les moteurs. **Un
déclenchement de cycle est un pilotage**, même s'il passe par LinuxCNC.

### D84 — Simulation ouverte, matériel conditionné à la qualification

Les conditions de dépôt, dans l'ordre — et l'ordre porte du sens :

1. **porte de sécurité** : le programme vient d'une gamme approuvée sous le
   setup courant. Si l'état ne l'autorise pas, rien d'autre n'a d'importance ;
2. **géométrie mesurée** : les pivots ne peuvent pas être provisoires ;
3. **concordance des dossiers** : la calibration déposée est celle sous
   laquelle l'approbation a été donnée ;
4. **destination matérielle** : elle exige en plus une machine **qualifiée** sur
   pièce d'épreuve mesurée.

Le point 4 est la seule condition que le logiciel ne peut pas satisfaire seul,
et c'est voulu : personne ne devrait pouvoir lancer une production depuis un
logiciel qui n'a jamais vu une pièce sortir de cette machine.

Le dépôt en **simulation** reste ouvert dès que 1 à 3 sont remplies. Y mettre
les mêmes exigences qu'au matériel empêcherait de vérifier la chaîne, donc
rendrait la qualification **inatteignable** — une porte qui se verrouille sur
sa propre clé.

### D85 — Le fichier déposé porte sa provenance

Setup, calibration, empreinte SHA-256 du contenu et horodatage sont écrits
**dans** le programme, en commentaires, en plus du journal de dépôt. Un fichier
récupéré sans son journal doit pouvoir être rattaché à son dépôt — sinon on
retrouve un `.ngc` sur une clé USB sans savoir de quelle machine, de quel
montage ni de quelle calibration il vient.

---

## 3. Ce que M9 ne lève pas

| Limite | Pourquoi |
|---|---|
| ~~Configuration non validée par LinuxCNC~~ | **levée** : 2.9 compilée depuis la source, configuration chargée, cinq défauts trouvés et corrigés ([note](../validation-linuxcnc.md)) |
| **Justesse numérique de la cinématique** | le démarrage ne dit rien de l'accord entre `xyzacKinematicsInverse` et le solveur de ce projet. C'est le travail qui suit |
| **Signe des offsets de pivot** | aucune simulation ne l'établit : il faut commander un déplacement et regarder. Le module prévient lui-même que « the directions of the rotational axes are the opposite of the conventional axis directions » |
| **Machine non construite ni qualifiée** | inchangé depuis M7 ; c'est la condition du dépôt matériel |
| Noms des broches HAL de la cinématique | dépendent de la version : à confirmer par `halcmd show pin xyzac` |
| Signe des offsets de pivot | exige `AXIS_DIRECTION`, donc la machine |
| Prise d'origine, table d'outils | exigent `WIRING_TEST` et des mesures de longueur |
| HAL matériel | la HAL produite est de **simulation** : articulations bouclées, aucun pilote de moteur. Le passage au matériel se fait machine devant soi |
| Démarrage de cycle | fermé par conception (D83) |

**±0,02 mm reste un objectif de qualification physique.**

---

## 4. Une remarque sur le mode d'échec

Ce jalon se distingue des précédents : il n'y avait **rien à mesurer** — aucun
moyen d'exécuter ce qu'il produit. Le travail a donc consisté à ranger ce qui
est produit par **degré de confiance** et par **mode d'échec** :

- ce qui échoue bruyamment (un nom de broche inconnu) peut être écrit avec un
  doute assumé, parce que l'erreur se signalera d'elle-même ;
- ce qui échoue silencieusement (un signe d'offset) ne peut pas être écrit avec
  un doute : il faut renvoyer à la procédure qui l'établit, et dire que le
  calcul ne la remplace pas ;
- ce qui n'a pas de valeur légitime (une prise d'origine, une jauge d'outil)
  reste vide **avec son motif écrit dans le fichier** — parce qu'un vide sans
  explication se fait remplir par le premier qui passe.

C'est une discipline utilisable partout où l'on livre quelque chose qu'on ne
peut pas tester : **classer par ce qui arrive quand on se trompe.**

---

## 5. Le seul défaut trouvé, et comment

Il n'a pas été trouvé par la mesure, faute de quoi mesurer, mais en **lisant la
sortie dans ses deux états côte à côte** — configuration non calibrée, puis
calibrée. L'en-tête de la section provisoire disait :

> `PROVISOIRE — deduit d'un modele non calibre :`

Sur une machine dont la géométrie **est** mesurée mais dont la pièce d'épreuve
manque, la section reste non vide, à bon droit — et l'en-tête annonçait « modèle
non calibré » juste au-dessus d'un pivot mesuré. Un opérateur qui lit cela peut
conclure que sa calibration n'a pas été prise en compte, et la refaire.

C'est le **trente-troisième** défaut du projet et la quatrième occurrence d'une
même famille, celle que M8 avait déjà nommée : **une phrase de catégorie écrite
d'avance, qui cesse d'être vraie quand l'état change.** Les trois précédentes
étaient une ligne d'en-tête de G-code annonçant un manque comblé depuis, une
note de recette contredisant la valeur qu'elle accompagnait, et un conseil de
remède pointant à l'envers.

L'en-tête énonce désormais ce qui est vrai des deux entrées possibles — « ce
qu'aucune mesure n'établit à ce jour » — et un test vérifie qu'une
configuration calibrée n'est jamais qualifiée de non calibrée, tandis que le cas
non mesuré continue de nommer le sien.

La règle de M8 se précise : **une phrase qui classe doit être aussi vraie que
l'entrée la plus favorable qu'elle peut coiffer.** Un en-tête n'est pas un
commentaire ; c'est une affirmation portant sur tout ce qu'il surplombe.
