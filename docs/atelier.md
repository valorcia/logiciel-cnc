# L'Atelier — l'interface de l'utilisateur

## 1. Ce que c'est, et ce que ce n'est pas

Le **banc de debug** (`docs/banc-de-debug.md`) montre ce que le moteur
*calcule*. L'**atelier** montre ce que l'utilisateur *doit faire*. Ce ne sont
pas deux présentations du même écran : l'un sert à trouver un défaut, l'autre à
décider.

Et il sert d'abord à **décider de la mécanique avant de la construire** : les
cotes que vous n'avez pas encore coulées dans le métal — courses, débattement
de la bascule A, rayon du plateau, outil — sont des champs modifiables. Changez
une cote, relancez, regardez ce que cela change sur une vraie pièce. C'est ce
que la simulation permet de faire à ce stade, et c'est ce qui coûte le plus
cher à découvrir après.

> **SIMULATION UNIQUEMENT.** Aucune machine n'est reliée à cette fenêtre. Un
> test vérifie, sur l'AST de tous les modules de l'atelier, qu'aucun n'importe
> `linuxcnc_gateway`, `socket`, `serial` ou `linuxcnc`. Le serveur n'écoute que
> sur la boucle locale.

## 2. Lancer

**Double-cliquez** sur `demarrer-atelier.bat` (Windows) ou
`demarrer-atelier.command` (macOS / Linux). En ligne de commande, c'est le même
fichier :

```bash
python tools/demarrer_atelier.py
```

Il trouve Python, crée un `.venv` à côté du logiciel, installe `[atelier]` si
nécessaire, fabrique les exemples s'ils manquent, puis démarre. La première fois
demande environ **300 Mo** de bibliothèques — mesuré sur une installation neuve,
pas estimé ; les suivantes sont immédiates. Effacer le dossier `.venv` annule
tout, sans rien laisser ailleurs.

Les deux lanceurs ne portent **aucune** logique : un `.bat` ne s'éprouve pas
sur une machine Linux, un `.command` ne s'éprouve pas sur Windows, et s'ils
installaient eux-mêmes, la moitié de ce que reçoit l'utilisateur ne serait
jamais essayée. Ils trouvent Python et passent la main au script Python, qui
est le même partout. Un test le vérifie.

À la main, si vous préférez :

```bash
pip install -e ".[atelier]"
python -m xyzac.ui.atelier
```

`[atelier]` et non `[ui]` : le serveur est en bibliothèque standard et les vues
sont rendues hors écran, donc Qt n'y sert à rien — c'est ~200 Mo qu'un
Raspberry Pi n'a aucune raison de porter.

L'atelier **contrôle le rendu 3D au démarrage**, par une vraie image de 32 × 32
pixels et non par un `import` : un import qui réussit ne dit pas qu'une image
sortira, et sur un Pi sans écran c'est le pilote qui manque, pas la
bibliothèque. S'il ne peut pas rendre, il le dit dans le terminal **et sur la
page**, avec la commande à taper. Avant, la panne arrivait à la première vue,
sous la forme d'une image vide muette et d'une trace visible du seul terminal.

Le navigateur s'ouvre sur `http://127.0.0.1:8765/`. `Ctrl+C` pour arrêter.

Pas de navigateur (Pi en SSH) : `--sans-navigateur`, puis ouvrez l'adresse
depuis votre poste avec un tunnel `ssh -L 8765:127.0.0.1:8765 pi@…`.

## 2bis. Un écran de 10 pouces, donc cinq pages

La cible est un écran de **10 pouces** (1280 × 800 typiquement), posé près de
la machine. Cinq cartes empilées y donnaient une page de 5 000 pixels de haut
dont quatre cinquièmes étaient inaccessibles — et la barre pour avancer se
retrouvait hors de portée.

L'atelier est donc un **assistant paginé** : une étape par écran, les autres
absentes (et non grisées : griser quatre étapes remplit l'écran de choses à
ignorer). La coquille est fixe — en-tête, fil d'étapes, bandeau de la pièce,
barre de navigation — et **seul le contenu de l'étape défile**, ce qui garantit
que le bouton pour avancer est toujours à l'écran.

Ce n'est pas une intention, c'est une exigence **mesurée** : l'épreuve
navigateur tourne en 1280 × 740 et demande au navigateur où se trouvent la
barre de navigation, le fil, la vue 3D, le lecteur, les puces d'axes et les
réserves. Chacun doit être dans la fenêtre. Vérifier que « la page ne déborde
pas » ne dirait rien — une coquille en `overflow:hidden` ne déborde jamais,
même quand elle coupe son contenu.

Deux conséquences de forme :

- **Le bandeau de la pièce est hors des pages.** Il vivait dans l'étape 1, donc
  il disparaissait dès qu'on avançait. Savoir quelle pièce est chargée vaut à
  chaque étape.
- **Les gros boutons s'effacent quand leur résultat est là**, remplacés par un
  lien (`revérifier`, `recalculer la simulation`) : ils ont servi, et sur les
  étapes chargées ils prenaient la place de ce qu'on vient lire.
- **En paysage, les commandes passent à côté de la vue** (au-delà de 1080 px de
  large) : la hauteur manque, la largeur abonde. La réserve longue est repliée
  derrière « ce qui n'est pas montré », mais ce qui **change une décision**
  reste à l'écran en une ligne — deux champs calculés, et non une phrase
  tronquée : une réserve coupée en deux ne se lit plus.

## 3. Les cinq étapes

1. **Votre pièce** — glissez votre fichier `.step` ou `.stp` sur la page, ou
   choisissez-le avec le bouton. Clé USB, pièce jointe, dossier de CAO : le
   fichier passe par l'importeur **contrôlé** du moteur, celui qui refuse une
   coque non fermée en disant pourquoi. Vous n'avez pas encore de fichier ? Un
   volet replié prête 20 géométries d'exemple, plus 3 volontairement abîmées —
   voir ce que le logiciel fait d'un mauvais fichier vaut mieux que le
   découvrir avec le sien.
2. **Regardez** — la pièce sur le plateau, dans la machine. Quatre boutons
   pour tourner la vue.
3. **Cette machine peut-elle faire cette pièce ?** — le moteur essaie les six
   façons de poser la pièce et répond **surface par surface**, chaque surface
   nommée par ce qu'on peut montrer du doigt (« le dessous », « le flanc
   droit ») et chaque verdict assorti d'une action. Un volet replié,
   *« ma machine n'a pas ces cotes »*, donne les neuf réglages : ce sont ceux
   qui changent l'**accessibilité**, les avances changent le temps d'usinage
   et pas la faisabilité.
4. **Regardez-la s'usiner** — voir §3bis.
5. **Lancer** — voir §3ter.

Les étapes 2 à 5 restent grisées tant qu'aucune pièce n'est chargée, et disent
pourquoi. Un bouton qui ne répond pas est pire qu'un bouton absent.

### 3bis-0. Les résultats arrivent en direct

Avant : **51 secondes devant une barre de progression**, puis tout d'un coup.
Or le moteur décide les surfaces **une par une** — garder le résultat de la
première pendant qu'on calcule la sixième fait attendre pour rien.

Mesuré sur la pièce d'essai (C05, six surfaces) :

| | avant | après |
|---|---|---|
| la liste des surfaces apparaît | 51 s | **2,8 s** |
| premier verdict | 51 s | **5,2 s** |
| trois verdicts sur six | 51 s | **14,3 s** |
| résultat complet | 51 s | 51 s |

Le total ne change pas — ce qui change, c'est que l'attente n'est plus aveugle.

Trois décisions :

- **La liste est complète dès la première seconde**, verdicts vides. Les noms
  ne dépendent que des normales moyennes, donc ils sont déjà connus. Faire
  apparaître les lignes une par une ferait bouger la liste sous le curseur au
  moment où l'opérateur la lit.
- **Une surface non décidée n'est jamais dite « impossible ».** Tant que les
  six montages ne sont pas dépistés, « aucun montage ne la couvre » est une
  *absence* de conclusion, pas une conclusion. Afficher « impossible » à la
  première seconde pour le corriger à la cinquantième serait pire que de faire
  attendre. Un test l'exige.
- **Un seul code pour les deux chemins.** `_rediger` (final) n'est qu'un appel
  à `publier(..., complet=True)`. Écrites séparément, la version affichée en
  direct et la version finale auraient divergé — et c'est la version affichée
  que l'opérateur aurait lue.

Le résumé partiel le dit lui aussi : *« 3 surfaces décidées sur 6 — analyse en
cours »*, et **aucune réserve n'est affichée sur un résultat partiel** : les
réserves bornent un résultat, pas un chantier.

### 3bis-a. Le verdict est relié à la géométrie

Manque le plus coûteux de l'interface jusqu'ici : le verdict disait *« le
flanc arrière — à changer »* et **rien ne montrait de quelle surface il
parlait**. Sur une pièce à dix-huit faces, les noms se répètent (« le
dessus (2) ») et une liste ne se rattache à aucune géométrie. Lire un verdict
qu'on ne peut pas situer ne sert à rien.

Cliquer une ligne **allume la surface sur la pièce**, dans la couleur de son
verdict — les trois mêmes teintes que les pastilles, prises du code couleur du
moteur. La liste est à gauche, la pièce à droite et collante : la question est
« laquelle est-ce ? », et y répondre demande de voir les deux en même temps.

Trois décisions, chacune prise en regardant une capture :

- **Les points affichés sont ceux que le solveur a interrogés**, gardés et non
  recalculés. Un contour redessiné pour l'affichage pourrait différer de ce qui
  a été jugé, et l'opérateur verrait une surface verte à l'endroit d'un refus.
- **La caméra se tourne vers la surface**, depuis sa normale moyenne. La
  première version nommait « le dessous » en montrant le dessus : les marques
  étaient cachées derrière la pièce. Une vue qui nomme une surface sans la
  montrer ne désigne rien.
- **La pièce passe au gris sur cette vue.** L'orange d'un « à retourner » se
  confondait avec l'ambre de la pièce — indistinguables sur la capture. Sur
  cette vue le sujet est la surface, pas la matière.

### 3bis-b. « Et avec quel outil, alors ? »

C'est la question que posait tout refus, et l'atelier n'y répondait pas. Il
disait *« un outil deux fois plus fin ne suffirait pas non plus »* — vrai, et
ce n'est pas une cote à commander.

Sélectionner une surface qui bloque lance une **dichotomie sur le diamètre**
(pas sur un bouton à trouver : la question se pose d'elle-même). Elle cherche
le plus gros outil qui franchit les points refusés, avec la géométrie de
porte-outil réelle. Coût mesuré : **0,3 à 3 s**, deux à sept résolutions.

Trois réponses possibles, et elles sont distinctes :

| cas | réponse |
|---|---|
| les points sont bloqués par le **montage** | *« même une machine sans limite de course les atteindrait — changer d'outil n'y ferait rien »* |
| un diamètre passe | *« un outil de Ø 0,9 mm franchit ces points, là où le vôtre de 6 mm ne passe pas »* |
| aucun, même 0,4 mm | *« ce n'est plus une question d'outil mais de dessin »* |

**Et l'asymétrie du test est portée par le résultat.** Le test de collision est
une borne supérieure (ADR-001 / D2) : il voit un outil de rayon *r* comme un
outil de rayon *r + δ*. Donc

- **« ce diamètre passe » est fiable, et même prudent** — le vrai diamètre
  admissible peut être plus gros. Le dire évite de faire acheter un outil plus
  fin que nécessaire ;
- **« aucun diamètre ne passe » est indécidable** dès que le rayon essayé est
  comparable à δ : c'est peut-être le gonflement seul qui bloque. Le résultat
  le dit, et renvoie à une pièce d'essai.

Ma première version avait cette inégalité **à l'envers** : elle déclarait non
concluant un diamètre de 2,4 mm sous un gonflement de 1,26 mm, alors qu'un
passage mesuré est précisément ce dont on peut être sûr.

Deux autres défauts corrigés sur les captures :

- je diagnostiquais *« ce n'est plus une question d'outil mais de dessin »*
  pour une surface dont les six points sont bloqués par le **montage** — elle
  regarde le plateau. Le moteur distingue les deux causes et je venais
  d'écraser la distinction ;
- la consigne de la ligne concluait *« ajoutez un congé »* depuis le seul
  sondage à moitié de diamètre, **en contradiction** avec le diagnostic qui
  trouve parfois un diamètre qui passe. Deux phrases vraies qui se
  contredisent valent moins qu'une seule qui renvoie à la mesure.

Et les **points refusés sont marqués sur la pièce**, plus gros et en plein, la
surface elle-même restant en transparence — sur une surface refusée, les deux
étaient du même rouge et le « où exactement » disparaissait dans le
« laquelle ».

### 3bis. La simulation d'usinage

Ce n'est **pas** un tour de manège autour de la pièce. La caméra ne bouge pas ;
c'est l'outil qui parcourt la trajectoire que `plan_roughing` a réellement
calculée, avec les A/C que ce plan a choisis, et la trajectoire déjà parcourue
se dessine derrière lui. Sous chaque image : X, Y, Z, A, C de la pose, si
l'outil coupe ou se déplace en rapide, et **s'il sort des courses réglées** —
ce dernier point a trouvé un cas réel dès le premier essai (plan de dégagement
à Z = 62 mm pour une course qui s'arrête à 60).

Les passes de **finition** ont rejoint le film, après l'ébauche — voir
§ 3bis-c, y compris pour le cas fréquent où il n'y en a aucune à montrer.

Ce que la simulation **ne** montre **pas**, et qu'elle écrit sous elle, chiffré
depuis l'état réel :

- la **matière qui disparaît** — la pièce finie est dessinée dès la première
  image ;
- les **brides**, qui ne sont modélisées nulle part dans le projet ;
- la matière restante, séparée en deux : celle qu'**aucune** indexation
  candidate ne voit (il faut reposer la pièce) et celle que l'aperçu laisse
  parce qu'il **se limite à 2 indexations** pour tenir en quelques secondes.

### 3bis-c. L'orientation de finition : cherchée, pas déduite

C'est la finition qui fait la pièce : c'est elle qui donne l'état de surface,
elle qui passe au plus près. Le film la montre donc, après l'ébauche — mais
seulement quand une orientation a été **vérifiée**.

**Le défaut mesuré, et ce qu'il enseigne.** La première version prenait la
*normale moyenne* de la surface et en tirait le couple (A, C) par cinématique
inverse. C'est séduisant et c'est faux. Mesure sur le flanc avant de
`C05_ailettes_rapprochees` : A = −90°, C = 0° ne dégage qu'en **1,2 % des
points**. La normale moyenne dit où **regarde** la surface ; elle ne dit rien
de ce que l'outil rencontre en chemin — ni le berceau, ni le porte-outil, ni le
rayon local. C'est la même faute que six autres dans ce projet : *lire une
grandeur voisine de celle qu'on veut*.

**Ce qui a remplacé ça.** `decide_indexed_pass` (moteur M10, pas l'IHM) sonde
8 points en résolution complète, intersecte leurs ensembles admissibles pour
obtenir des **candidats**, puis vérifie chaque candidat en chaque point examiné.
Une passe n'est animée que si un candidat dégage **partout** sur l'échantillon.
Sur `C01_bloc_simple`, le dessus sort ainsi à **A = 24°, C = −180°, dégagement
15,0 mm** — et non à A = 0 comme la normale l'aurait dicté.

**La portée est affichée avec la mesure.** Le champ d'obstacles fait
50 881 points sur C05, et `verify_direction` y coûte 31 ms par point : les
7 909 points d'une passe demanderaient quatre minutes *par orientation
essayée*. 150 points répartis sont donc examinés, et le titre de l'image le
dit : « orientation vérifiée en 150 points répartis sur les 5 278 de la
passe ». Une vérification sur échantillon est une mesure **optimiste** ; écrire
« vérifiée » sans écrire « sur 150 » promettrait une preuve là où il y a un
sondage.

**Quand il n'y a rien à montrer, c'est dit.** Sur C05, **aucune** des six
surfaces n'a d'orientation qui dégage dans le montage de départ. La simulation
n'anime alors aucune finition, et nomme chaque refus avec son motif *et son
remède*, rendus par le moteur :

> « Le dessous » — 8 des 8 points sondés ne sont atteignables par AUCUNE
> orientation : ni 3+2 ni simultané ne passeront là. Ce qui bloque : aucun
> couple (A, C) ne réalise l'orientation requise : cette face demande un second
> montage.
>
> « Le dessus » — 4 des 8 points sondés ne sont atteignables par AUCUNE
> orientation […]. Ce qui bloque : le porte-outil touche : allonger la jauge.

Une animation de 1 % de couverture ressemble à un usinage : c'est ce qui la
rend dangereuse, elle ne se remarque pas. Un refus nommé, si.

**Deux pages, deux questions — et la contradiction apparente est dite.** La
vérification (étape 3) essaie **six montages** : « usinable » peut vouloir dire
« usinable une fois retournée ». La simulation, elle, ne sait dessiner que le
montage de départ. Trois surfaces de C05 sont donc jugées usinables sans avoir
de finition animée, et la note l'énonce — *« 3 surfaces jugées usinables,
0 avec une orientation dans le montage de départ : retourner la pièce n'est pas
encore simulé »* — plutôt que de laisser deux pages se contredire à l'écran.
Cette phrase est **calculée** depuis les deux comptes : elle disparaît d'elle
même le jour où le remontage sera simulé.

### 3bis-d. Les courses linéaires, et la pièce qu'on repose de 6 mm

**Le défaut.** Le planner filtrait les indexations sur les courses A et C,
avec ce commentaire : *« une direction que le berceau n'atteint pas n'est pas
une option, quelle que soit la matière qu'elle verrait »*. L'argument est
juste — et il valait tout autant pour X, Y et Z, où personne ne le tenait.
Mesure sur `C05_ailettes_rapprochees` : le planner retenait A = −90°, C = −90°
pour le volume qu'elle enlève, et la trajectoire sortait de la course Y sur
**3 974 de ses 18 249 positions**, avec 6 mm de dépassement. Rien ne le disait.
Un programme qui contient des positions hors course ne s'arrête pas à la
simulation : il s'arrête à la machine, en pleine matière.

**Le fait que personne ne peut deviner.** À A = −90° le berceau couche la
pièce, et son pivot est 40 mm sous le plateau : un point à la hauteur `z` se
retrouve en `Y = z + 40`. Les 53 mm de la pièce, plus 25 mm de cales, plus
40 mm de pivot font 118 mm pour une course de 120 — et le plan de dégagement
achève de sortir. **Sur une machine XYZAC, la hauteur de la pièce se paie en
course Y dès que le berceau bascule.**

**Un verdict exact, pour une fois dans les deux sens.** Le domaine des courses
est une *boîte*, donc convexe : un segment dont les deux extrémités tiennent
tient entièrement, et tester les sommets de la polyligne suffit. Rien n'est
échantillonné, il n'y a donc aucune réserve à énoncer — c'est le seul test du
projet dans ce cas. Le test d'*enveloppe* (les huit coins d'une boîte), lui,
reste asymétrique et ne sert qu'à renseigner.

**Ce que la mesure m'a fait défaire.** J'avais d'abord classé les indexations
dont l'enveloppe tient en tête. Sur la poche C02, cela rétrogradait `+Z` —
36 028 mm³, l'indexation naturelle — pour **1 mm** de dépassement sur une boîte
englobante, et le plan tombait de 40 % à 31 % de matière. Or « la boîte ne
tient pas » ne prouve rien sur la trajectoire. **Agir sur une non-conclusion
est une faute, même quand elle va dans le sens de la prudence.** Le classement
reste donc volumique, et c'est la mesure exacte — après tranchage — qui écarte.

**Une indexation hors course est écartée, pas signalée.** Et son rejet est
rapporté avec ce qu'il coûte : sur C02, `+Z` est écartée pour **0,2 mm**, et
c'était la plus riche des cinq. Le planner mesure aussi la course *avant* de
consommer la matière, sinon les indexations suivantes verraient un brut entamé
par une opération qui n'existe pas. Et `max_setups` borne désormais les
opérations **retenues** et non les tentatives : un rejet réduisait
silencieusement la gamme.

**Le remède est calculé, puis proposé en un bouton.** Un dépassement est une
translation, donc il se corrige en décalant la pièce, et le décalage se
calcule : `R_machine←pièce^T · t_machine`, arrondi au centième **par excès**
(arrondi vers le bas, il laisserait la trajectoire à un centième de la butée).
L'atelier l'offre :

> Reposer la pièce −6.0 mm en Z rendrait utilisable une indexation qui voit
> 163 224 mm³ — vérifiez qu'elle ne touche alors ni le plateau ni le berceau.
> **[ Reposer la pièce ainsi ]**

Mesuré sur la boucle réelle : C05 passe de **aucun programme du tout** à
**2 opérations d'ébauche, 60 % de matière enlevée**, en **un clic**.

**Et un remède impraticable est écarté.** La boucle proposait ensuite −24 mm,
soit des cales à −30 mm pour une pièce posée sur 25 mm : la pièce enfoncée de
5 mm *dans* le plateau. Le calcul de course ne regarde pas le plateau et le
dit ; c'est donc à l'atelier, qui connaît la pose, de refuser — *« il n'est pas
praticable : il faut une course plus longue, des cales plus hautes au départ,
ou une pièce moins haute »*. Un remède impraticable est pire qu'un constat : il
fait démonter un montage pour rien.

Deux cas se distinguent, d'ailleurs, et ne se corrigent pas pareil : une pièce
*décalée* sort par un bout, et la translation la rattrape ; une pièce plus
*longue* que la course sort par les deux bouts, et translater ne fait que
changer le bout qui dépasse.

**La pose déclarée est un fait du montage**, affiché en permanence dans la
fiche de la pièce (« pièce reposée de −6.0 mm en Z »), et non un message qui
disparaît avant le calcul qu'il explique. Le décalage s'**ajoute** à la pose
suggérée : le remettre à zéro retrouve exactement la pose de départ, et non une
pose dérivée des essais successifs.

**La finition passe le même examen.** Le solveur d'accessibilité connaît
`MACHINE_TRAVEL` et le vérifie *aux points examinés* ; la trajectoire passe
aussi ailleurs. Sans mesure des courses sur ses sommets, la finition était
animée là où l'ébauche aurait été refusée — sur le même écran.

### 3bis-e. « On ne peut pas entrer là » : la collision d'approche

Le contrôle des courses a fait apparaître d'un coup un défaut plus ancien :
**l'indexation d'ébauche était choisie sans aucun contrôle de collision.**
Volume, puis cinématique, puis (depuis peu) courses — jamais collision. Ça ne
se voyait pas parce que l'indexation du dessus, la plus riche, passait
toujours en premier ; le jour où elle a été écartée pour 2 mm de course, les
indexations latérales sont sorties, et avec elles le problème.

Mesure sur la poche C02, fraise de 45 mm de jauge : à A = −90° le **nez de
broche traverse le brut** pendant l'approche — 0,26 mm de pénétration au
premier segment, 6,5 mm au suivant. Le plan la retenait.

**La porte, et ce qu'elle contrôle exactement.** Les trois sommets de chaque
bout du programme : le plan de dégagement, la descente, le premier point de
coupe. Ce sont les segments qui traversent le vide vers la matière, ceux où un
contact est un **choc** et non une coupe. Le contrôle se fait sur l'état
**réel** du brut — le brut intact est une borne supérieure de la matière, donc
un refus fondé sur lui serait parfois pessimiste.

**Seuls comptent les organes qui ne doivent JAMAIS toucher** : tige, col,
porte-outil, nez de broche. Ma première version comptait tout contact, y
compris `cutting / PART`, et écartait donc l'indexation du dessus **pour avoir
coupé**. L'arête de coupe est faite pour toucher la matière ; combien l'ébauche
entame la pièce finie est une autre question, et elle a sa propre mesure
(`gouged_voxels`).

**Ce que cette porte ne couvre pas**, et il faut le dire franchement : les
segments de **coupe**. Le balayage coûte 22 ms par sommet mesuré, soit près de
huit minutes pour les 20 724 sommets d'une trajectoire d'ébauche — hors de
portée d'un aperçu. Une collision tige/pièce en pleine coupe reste invisible
ici. C'est une **limite déclarée**, pas une délégation : rien d'autre ne la
vérifie à ce jalon, et c'est l'une des raisons pour lesquelles la porte de
production refuse tout dépôt vers une machine réelle.

**Le résultat, bout en bout, sur la poche C02** (ballnose Ø 6, jauge 45) :

| pose | matière enlevée | ce que l'atelier dit |
|---|---|---|
| cales 25 mm (suggérées) | **2 %**, 1 opération | +Z écartée pour 2,0 mm de course Z ; 3 latérales écartées, l'outil ne peut pas y entrer |
| cales 23 mm (**un clic**) | **30 %**, 2 opérations | 1 latérale encore écartée (porte-outil dans le brut) |

Un clic sur « Reposer la pièce ainsi » fait passer la gamme de 2 % à 30 %, sans
gouging. C'est ce que cette page cherche à être : pas un logiciel qui dit non,
un logiciel qui dit **quoi changer**.

**Ce qui a été retiré à l'affichage.** « 15 images sur 36 hors courses »
comptait les 36 poses échantillonnées pour l'animation : un chiffre qui dépend
du nombre d'images demandées, pas de la gamme. C'était encore la même famille
de faute — *lire une grandeur voisine de celle qu'on veut*.

### 3bis-f. Le temps de cycle, annoncé comme un plancher

**« au moins », jamais « environ ».** Le calcul suppose que chaque axe atteint
son avance dès le premier millimètre et la tient jusqu'au sommet suivant. Ce
qui manque est nommé, et pèse : les **accélérations** et le ralentissement dans
les angles — une ébauche en zigzag change de sens à chaque rangée —,
l'anticipation, les **changements d'outil**, la mise en vitesse de broche, le
**palpage** et les reprises entre montages. Le chiffre est donc
systématiquement optimiste. C'est la même règle que pour ±0,02 mm : un objectif,
pas un acquis.

**L'avance n'est pas inventée.** Elle vient de `recipe_profiles.build_recipe`,
c'est-à-dire de la matière déclarée, de l'outil et de la machine — déjà bridée
par les courses d'avance des axes et déjà **réduite de moitié** faute de
qualification (ADR-007). Quand la matière n'est pas dans la table, il n'y a
**pas de temps affiché** : `recipe_profiles` refuse de deviner les paramètres
d'une matière voisine, et un temps calculé sur une avance inventée serait la
fausse valeur type.

**L'avance de rapide dépend de la DIRECTION**, et le calcul se fait dans le
repère machine. Une diagonale n'est pas plus rapide que son axe le plus lent :
`min_i (V_i / |d_i|)`. Les longueurs, elles, sont les mêmes dans les deux
repères (une rotation conserve les distances) — mais un déplacement selon X de
la pièce, à A = −90° et C = −90°, est un déplacement selon **Y** de la machine,
avec une autre avance maximale. Une réindexation compte le **maximum** de A et
C, pas leur somme : les deux axes partent ensemble, et les additionner
surestimerait — incohérent pour un minorant déclaré.

**Ce que le chiffre a immédiatement révélé.** Sur la poche C02 en
aluminium 6061 :

| poste | longueur | temps |
|---|---|---|
| coupe | 8 735 mm à 517 mm/min | 17 min |
| **déplacements rapides** | **140 838 mm** | **42 min** |
| rotation (2 réindexations) | — | 2 s |

**29 % du temps seulement est passé à couper.** 140 mètres de transport pour
8,7 mètres de coupe. La cause est mesurée : la trajectoire remonte au plan de
dégagement et redescend **1 197 fois**, parce que la région à évider d'une
poche est annulaire et que chaque rangée y est coupée en deux tronçons par la
paroi. Relier deux tronçons à la profondeur de coupe traverserait la pièce, donc
le trancheur remonte — et il a raison. C'est le prochain levier, et il est
gros : router la liaison *dans* la région valide, ou ne remonter qu'à la hauteur
réellement nécessaire plutôt qu'au plan de dégagement global. Ce chantier n'est
**pas** fait ; le décompte par poste est là pour qu'il ne se perde pas.

### 3bis-g. Le bridage, enfin déclaré

`Fixture` existe depuis le jalon M1 et `build_scene` échantillonne les bridages
depuis toujours. **Personne n'en déclarait.** L'atelier construisait un montage
sans bridage et le disait — *« les brides ne sont pas modélisées du tout »* —,
donc tous les verdicts d'accessibilité étaient optimistes, et cette réserve
revenait sous chaque résultat sans que rien ne permette de la lever.

Ce qui manquait n'était pas le modèle mais le **chemin** : personne ne saisit
huit coordonnées de boîte sur un écran de 10 pouces. L'atelier part donc de ce
qu'un opérateur sait de son montage :

- **étau** — la prise en mm (mesurée depuis le *dessous* de la pièce, comme on
  serre) et l'axe de serrage ;
- **brides sur plateau** — combien, leur hauteur, et ce qu'elles **recouvrent**
  du bord : c'est la cote qui interdit d'usiner cette bande, et celle qu'on
  oublie en posant ses brides ;
- **aucun bridage déclaré** — le défaut, et il est assumé : supposer un bridage
  serait pire, cela ferait rejeter des orientations au nom d'un obstacle que
  personne n'a posé. Ce qui compte est de dire dans lequel des deux cas on est.

**Le sens de l'erreur est FAVORABLE, et c'est à dire.** Une boîte surestime un
bridage réel (un étau a des mors chanfreinés, une bride est une pièce mince sur
entretoise). Surestimer ajoute de l'obstacle, donc **retire** des orientations :
« cette orientation dégage avec le bridage déclaré » est fiable et même
prudent ; « elle ne dégage pas » peut être pessimiste. C'est l'inverse du
décalage de pièce (§ 3bis-d), dont l'erreur va dans le sens défavorable — et
confondre les deux ferait prendre un refus prudent pour un refus définitif.

**Rien d'autre à brancher.** Mesuré : déclarer un étau change le champ
d'obstacles, donc le solveur d'accessibilité, la porte d'entrée en matière et
la vérification de finition, qui le lisent tous. Le motif de refus passe de
`holder / STOCK` à `spindle_nose / FIXTURE` — le mors est devenu un obstacle
que le moteur voit.

Et la réserve **disparaît d'elle-même** : « les brides ne sont pas déclarées »
est calculée, remplacée quand un bridage existe par *« Bridage pris en compte —
Étau, pièce prise sur 12 mm selon X »*. Une phrase qui décrit un manque survit
à la disparition du manque si on ne la calcule pas.

### 3ter. Le bouton LANCER

Il ne fait pas partir la machine, et **aucun bouton de ce logiciel ne le
fera** : déposer un fichier programme puis laisser l'opérateur l'ouvrir et
appuyer garde un humain dans la boucle au dernier moment, celui où l'on regarde
la machine avant qu'elle bouge.

Ce qu'il fait : il affiche les **quatre conditions** à remplir, et ce qu'il faut
faire pour chacune. Aujourd'hui les quatre sont non remplies, parce qu'une
machine en kit qu'on vient d'assembler n'a ni gamme approuvée ni dossier de
calibration. C'est exact, et il n'y a aucune raison de l'habiller.

Ces conditions ne sont **pas** écrites dans l'interface. Elles viennent de
`xyzac/production_gate.py`, c'est-à-dire du même endroit que celui où
`linuxcnc_gateway.deposit` les fait respecter en refusant. Écrites deux fois,
elles auraient fini par diverger — et la copie divergente aurait été celle
qu'on lit à l'écran, donc celle sur laquelle quelqu'un se serait fié. Un test
(`test_the_page_and_the_deposit_refuse_for_the_same_reasons`) les attache
l'une à l'autre.

## 3quater. Le design, et pourquoi il est clair

Retouche complète après un premier jet jugé « vraiment moche », et le reproche
était mérité : cinq cartes identiques empilées, tout au même poids
typographique, et une vue 3D sombre dans laquelle le porte-outil était une
tache noire sur un fond noir.

**Thème clair.** Le banc de debug est sombre et doit le rester : son dégradé
d'outil encode la gravité d'un contact, du clair (l'arête, qui *doit* toucher)
au sombre (le nez de broche, qui ne doit *jamais* toucher). Sur fond noir, les
deux extrémités de ce dégradé disparaissent. Un atelier se regarde de jour,
souvent debout ; les logiciels de CAO sont clairs, ce qui évite à l'œil de
changer de régime entre deux fenêtres. Seul le **fond** de la vue est réglable
(`capture(background=…)`) : le code couleur reste l'unique source.

**Une légende sous chaque vue**, parce que rien ne disait « bleu = le brut ».
Une image qu'il faut se faire expliquer n'informe pas. Les teintes viennent de
`ui.debug.palette` par le serveur : les recopier dans la feuille de style aurait
créé une deuxième vérité, et c'est la copie *affichée* qui aurait menti. Un test
interdit toute teinte en dur dans `style.css` et `app.js`.

**Un fil d'étapes** collant en haut, où une étape est « faite » quand ce qu'elle
produit *existe* — pas quand on l'a cliquée : un bouton pressé dont le calcul a
échoué n'a rien fait.

**Le même cadrage à l'étape 2 et à l'étape 4.** Le cadrage « machine »
englobait tout le volume de courses (300 × 240 × 180 mm), ce qui rendait une
pièce de 60 mm minuscule dans une cage en fil de fer — et la vue ne ressemblait
pas à celle de la simulation, alors que c'est la même scène. L'opérateur avait
deux images à réconcilier au lieu d'une à comprendre.

### 3quinquies. Le rendu de la vue 3D

Quatre changements, chacun décidé en comparant deux images plutôt qu'en
raisonnant :

- **Éclairage « light kit »** — trois sources et un remplissage. Sans lui la
  scène est plate : un dôme n'a plus de dôme, un porte-outil est une tache.
- **Anti-crénelage SSAA.** Les arêtes en escalier sont ce qui fait qu'une image
  « a l'air d'un logiciel ». Coût mesuré : **0,67 s par image** contre 0,42 s
  sans, soit environ dix secondes de plus sur une simulation de 36 images.
- **Réflexion spéculaire, et non PBR**, alors que le PBR est plus moderne.
  Mesure sur les deux images : le PBR fait virer l'ambre de la pièce vers
  l'olive et le gris du brut vers le brun, parce qu'il *recalcule* la couleur.
  Or ces teintes portent une signification, et une signification qui change de
  couleur selon l'angle de la caméra ne signifie plus rien. Le spéculaire
  ajoute un reflet **sans toucher à la teinte**.
- **Les liaisons au second plan** (opacité 0,28). Mesure : 1 615 remontées et
  descentes pour 12 700 segments de coupe. Au même poids que la coupe, elles
  formaient une palissade verticale qui cachait la pièce qu'on venait
  regarder. Elles restent visibles — ce sont elles qui portent les mouvements
  qui traversent la pièce quand ils sont mal générés.

Et le cadrage est **resserré de 1,6** : le cadrage porte sur les organes
machine, ce qui le rend stable à toute indexation A/C, mais le plateau et le
berceau sont bien plus grands qu'une pièce de kit. Vérifié sur les **20 pièces
du corpus** : zéro pixel de pièce au bord de l'image.

Le resserrage rapproche la caméra de son point visé, et n'emploie *pas*
`plotter.camera.zoom()` — mesure : `zoom()` agit sur l'angle de vue, que
`camera_position` ne transporte pas, donc le paramètre était sans effet et deux
cadrages différents rendaient deux images identiques au pixel. Un test le
verrouille.

## 4. Trois décisions de construction

**Serveur : bibliothèque standard de Python.** Pas Flask, pas FastAPI. Cet
outil doit démarrer sur le Raspberry Pi d'un acheteur de kit, en une commande,
sans rien installer de plus. Une dépendance de serveur web se paie à chaque
mise à jour, pour un service que `http.server` rend ici très bien.

**Vue 3D calculée côté serveur, envoyée en image.** Marche sans pilote
graphique — donc sur un Pi sans écran comme sur un portable — et sans charger
de bibliothèque 3D dans le navigateur.

**Le fichier téléversé arrive en corps brut, son nom dans un en-tête.** Pas de
`multipart/form-data` : l'analyser correctement demande soit une dépendance,
soit une centaine de lignes, pour transporter une seule chose que le corps brut
transporte tel quel. La taille est vérifiée sur `Content-Length` **avant**
lecture — mesurer après avoir lu laisserait n'importe quel envoi remplir la
mémoire du Pi. Le nom est reconstruit caractère par caractère côté serveur :
il vient de la machine de quelqu'un d'autre et n'a aucune raison d'être sain.

**La page ne demande rien au réseau.** Aucune balise ne pointe vers un domaine
extérieur, l'icône est en ligne dans le HTML. Elle fonctionne hors ligne, et un
test le vérifie.

## 5. La traduction est un travail, pas du décor

Le moteur dit `AXIS_LIMITS 24/24`. L'atelier dit : *« la bascule A ne va pas
assez loin pour présenter cette surface : il faut retourner la pièce »*. C'est
la même information et ce n'est pas le même lecteur.

Mais la traduction **n'ajoute rien** : chaque phrase correspond à un champ
calculé par le moteur, jamais à une appréciation. Et un test structurel exige
que **tout** motif de blocage que le moteur sait produire ait sa consigne —
sinon l'utilisateur reçoit un constat sans suite, la seule chose qu'une
consigne ne doit jamais faire.

Un exemple de ce que cela a coûté : le premier jet affichait, pour les deux
plus grandes surfaces du dôme, « le moteur ne sait pas trancher ici :
l'échantillonnage est trop grossier pour ce diagnostic ». Exact, et inutile.
La version actuelle donne toujours le motif principal du solveur — donc une
action — et mentionne l'indécision comme une réserve, à sa place.

## 6. Ce que l'atelier dit toujours de son propre résultat

- le verdict est établi sur **6 points sondés par surface** : il écarte, il ne
  garantit pas ;
- **aucun bridage n'est modélisé** : un bridage réel retire des orientations,
  donc le résultat est **optimiste** ;
- dès qu'il y a plus d'un montage : chaque remontage repositionne la pièce et
  **les erreurs s'additionnent** — aucune tolérance ne peut être annoncée d'un
  montage à l'autre.

## 7. L'éprouver

```bash
python -m pytest tests/test_ui_atelier.py -q        # session, serveur, langage
python tools/test_atelier_navigateur.py             # la page, dans un navigateur
```

Le second demande `playwright` et un navigateur, ce qui explique qu'il vive
dans `tools/` : il ne doit pas alourdir la suite du projet. Il clique
réellement sur les boutons, attend les images, lit les verdicts, et laisse ses
captures dans `out/atelier/`.

La pièce s'impose par `PIECE=` — et il vaut la peine d'en éprouver **deux**,
parce que plusieurs choses y ont deux issues, toutes deux à vérifier : la
finition (orientation trouvée ou refus nommé) et surtout la **simulation
elle-même** (programme produit ou aucun programme). Ce second cas a été trouvé
par cette épreuve : sur C05 aucune indexation ne tient dans les courses, donc
le lecteur n'apparaît jamais — et l'épreuve attendait dix minutes un élément
qui ne viendrait pas. C'est exactement le chemin où l'opérateur a le plus
besoin qu'on lui parle, et il n'avait aucune couverture navigateur.

```bash
PIECE=C01_bloc_simple.step           python tools/test_atelier_navigateur.py
PIECE=C05_ailettes_rapprochees.step  python tools/test_atelier_navigateur.py
```

Sur la première, une orientation de finition est trouvée et l'épreuve exige que
le titre de l'image dise **sur combien de points** la vérification porte. Sur
la seconde, aucune ne dégage dans le montage de départ, et l'épreuve exige que
le refus soit **nommé** — dans la ligne courte comme dans la note. Le silence
échoue dans les deux sens.

Résultat de la dernière exécution : fichier `.step` **téléversé** par le
sélecteur (60 × 60 × 25 mm, annoncé « votre fichier »), un `.txt` **refusé** en
clair, puis le dôme C10 chargé depuis les exemples, vue tournée, réglage
changé, **verdict en 46 s** — 4 surfaces usinables telles quelles, 1 après
retournement, 3 à changer —, **simulation d'usinage de 36 images** sur
22 587 points de trajectoire en 2 opérations d'ébauche (79 % de la matière
enlevée), lecture, pose d'axes affichée sous chaque image, puis les 4
conditions de lancement, toutes non remplies. **Aucune erreur dans la
console.**
