# Validation de la configuration par LinuxCNC

## 1. Pourquoi ce document existe

Le jalon M9 a été livré en affirmant : « aucun fichier produit par ce jalon n'a
été chargé par LinuxCNC, qui n'est pas installable dans l'environnement de
développement ». **La deuxième moitié de cette phrase était fausse**, et la
première n'était vraie que par conséquence.

Le diagnostic d'origine était : `apt install linuxcnc-uspace` → paquet
introuvable, et le dépôt de LinuxCNC répond 403 à travers le proxy. Les deux
constats étaient exacts. La conclusion tirée — « LinuxCNC est inaccessible » —
ne l'était pas : le 403 portait sur `ppa.launchpadcontent.net`, c'est-à-dire sur
les **paquets binaires**. Le dépôt source sur GitHub répond parfaitement, et
l'archive Ubuntu principale aussi, donc les dépendances de compilation
s'installent.

C'est une généralisation abusive d'un échec particulier : *un* canal était
fermé, et j'en ai conclu que *le* logiciel était hors d'atteinte. Le coût de la
vérification était de quelques minutes ; celui de l'erreur a été de livrer une
configuration portant cinq défauts.

## 2. La procédure, reproductible

Sur Ubuntu 24.04, en root, avec un accès réseau à `github.com` et à l'archive
Ubuntu :

```bash
# 1. source
git clone --depth 1 --branch 2.9 https://github.com/LinuxCNC/linuxcnc.git
cd linuxcnc/src

# 2. dépendances (sans la chaîne de documentation)
apt-get install -y --no-install-recommends \
  build-essential pkg-config autoconf automake libtool \
  bwidget gettext intltool libboost-python-dev libepoxy-dev libgl-dev \
  libglu1-mesa-dev libgtk2.0-dev libgtk-3-dev libmodbus-dev libgpiod-dev \
  libreadline-dev libedit-dev libtirpc-dev libusb-1.0-0-dev libxmu-dev \
  libudev-dev netcat-openbsd netpbm procps psmisc python3 python3-dev \
  python3-tk python3-xlib python3-opengl python3-cairo \
  tcl tcl8.6-dev tclx tk8.6-dev yapps2 xvfb

# 3. configuration — mode userspace, aucun noyau temps réel requis
#    PYTHON est forcé pour que la version de Python corresponde à celle
#    contre laquelle libboost-python est compilée (sinon les modules
#    Python de LinuxCNC plantent à l'exécution).
./autogen.sh
./configure --with-realtime=uspace --disable-check-runtime-deps \
            --disable-build-documentation PYTHON=/usr/bin/python3.12

# 4. compilation. `-k` parce que la génération des pages de manuel échoue
#    sur cette distribution, et qu'elle ne concerne aucun binaire.
make -k -j$(nproc)
```

Puis, pour exécuter sans matériel et sans écran :

```bash
. ./scripts/rip-environment
# rtapi_app refuse de tourner sous root : il exige un UID de repli non nul,
# et le répertoire de compilation doit être lisible par cet UID.
export RTAPI_UID=1000 RTAPI_FIFO_PATH=/tmp/rtapi_fifo

# (a) les broches réelles du module de cinématique
halrun -f <(echo 'loadrt xyzac-trt-kins'; echo 'show pin xyzac')

# (b) la configuration générée, en simulation, sous un écran virtuel
python tools/demo_m9_linuxcnc.py --out /tmp/cfg --calibrer
cd /tmp/cfg && xvfb-run -a linuxcnc -r /tmp/cfg/xyzac.ini
```

## 3. Ce que LinuxCNC a répondu

### 3.1 Les broches, mesurées et non supposées

```
xyzac-trt-kins.tool-offset
xyzac-trt-kins.x-offset          <- publiée, mais NON LUE par la cinématique xyzac
xyzac-trt-kins.x-rot-point
xyzac-trt-kins.y-offset
xyzac-trt-kins.y-rot-point
xyzac-trt-kins.z-offset
xyzac-trt-kins.z-rot-point
```

et, imprimé par le module lui-même au chargement :

```
xyzac-trt-kins coordinates=xyzac assigns:
   Joint 0 ==> Axis X     Joint 3 ==> Axis A
   Joint 1 ==> Axis Y     Joint 4 ==> Axis C
   Joint 2 ==> Axis Z
```

**C est l'articulation 4.** Le module accepte `coordinates=xyzabc`, qui donnerait
C = 5, au prix d'un axe B fictif à déclarer, borner et asservir pour rien.

### 3.2 La sémantique des broches, lue dans la source

`src/emc/kinematics/trtfuncs.c`, `xyzacKinematicsForward` et `…Inverse` :

- la rotation **C** se fait autour de `(x-rot-point, y-rot-point)` ;
- la rotation **A** se fait autour de
  `(y-offset + y-rot-point, z-offset + z-rot-point)` ;
- `x-offset` n'apparaît que dans `xyzbcKinematicsForward/Inverse` — pour la
  cinématique xyzac, c'est une broche morte ;
- en Z, seule la **somme** `z-offset + z-rot-point` intervient : les deux
  broches sont redondantes, et répartir une valeur mesurée entre elles n'aurait
  aucun sens.

Et, dans l'en-tête de `xyzac-trt-kins.c`, une phrase qui concerne directement
la question des signes :

> *The directions of the rotational axes are the opposite of the conventional
> axis directions.*

### 3.3 Les cinq défauts

| # | Défaut | Mode d'échec |
|---|---|---|
| 34 | **Aucune section `[HAL]` dans l'INI** : les deux fichiers HAL étaient écrits sur le disque et jamais chargés | `emcTrajInit failed`, démarrage impossible |
| 35 | **`x-offset` recevait la composante X mesurée de l'axe C**, broche que la cinématique xyzac ne lit pas | **silencieux** — calibration perdue sans aucun signe |
| 36 | **`y-offset` recevait la position absolue de l'axe C** au lieu de l'écart A↔C, et les `rot-point` restaient à 0 | **silencieux** — pivots faux |
| 37 | **`JOINTS = 6` et `[JOINT_5]`** alors que le module mappe C sur 4 ; `JOINT_AXIS` disait 4, la liste écrite à la main disait 5 | démarrage, bruyant |
| 38 | **Commentaires de `tool.tbl` en `#`** alors que le parseur attend `;` | `Unrecognized line skipped` à chaque ligne, à chaque démarrage |

Plus deux manques qui laissaient LinuxCNC choisir en silence :
`[TRAJ]MAX_ANGULAR_VELOCITY` (annoncé comme *required specifier*) et
`[EMCIO]CYCLE_TIME`.

### 3.4 Après correction

```
Found file(REL): ./xyzac.hal
note: AJOG max: 60.000 units/sec 3600.000 units/min
task: 1063 cycles, min=0.000009, max=0.019233, avg=0.010112,
      0 latency excursions (> 10x expected cycle time of 0.010000s)
```

et, interrogée pendant qu'elle tournait :

```
    33  User  inihal                    ready
    23  RT    motmod                    ready
    20  RT    xyzac-trt-kins            ready

    23  float OUT  0  joint.0.motor-pos-cmd ==> j0-pos
    ...                joint.4.motor-pos-cmd ==> j4-pos      (5 articulations)
    20  float IN -40  xyzac-trt-kins.z-offset
```

**La configuration démarre**, la cinématique est instanciée, les cinq
articulations existent, et la valeur mesurée est arrivée sur une broche réelle.

## 4. Ce que cela ne prouve toujours pas

- **Le signe des offsets de pivot.** Aucune simulation ne peut l'établir : il
  faut commander un déplacement sur la machine et regarder de quel côté la
  pièce part (`AXIS_DIRECTION`). L'avertissement du module cité en §3.2 rend ce
  point plus aigu, pas moins.
- **La justesse numérique de la cinématique**, c'est-à-dire que le
  `xyzacKinematicsInverse` de LinuxCNC et le solveur de ce projet placent la
  pointe d'outil au même endroit. Le démarrage ne dit rien de cela. Le
  recoupement chiffré des deux implémentations est le travail qui suit.
- **Le HAL matériel.** Le HAL produit est de simulation : articulations bouclées
  sur elles-mêmes, aucun pilote de moteur.
- **±0,02 mm**, qui reste un objectif de qualification physique.

## 5. La règle

Ces tests ne demandent pas LinuxCNC pour tourner
(`tests/test_m9_linuxcnc.py`), et c'était déjà le cas avant. Ce qui a changé
n'est pas leur nombre mais leur **objet** : ils vérifiaient le contenu de
chaque fichier, aucun ne vérifiait la **cohérence entre fichiers**. Le défaut
n° 34 en est la démonstration : `xyzac.hal` était juste, ligne par ligne, et
personne ne le chargeait.

> **Un ensemble de fichiers qui se tiennent la main n'est pas testé tant qu'on
> n'a pas testé les mains.**

Et, sur la méthode : un échec d'installation n'est pas un verdict
d'indisponibilité. Le second canal coûtait quelques minutes à essayer.

---

# Partie II — Le recoupement chiffré des deux cinématiques

Démarrer ne dit rien de l'endroit où LinuxCNC place la pointe d'outil. Un
mauvais offset de pivot démarre parfaitement et usine faux : c'est tout le
sujet de la décision D80. Il faut donc comparer des **nombres**.

## 6. Résultat

`tools/verify_kinematics_linuxcnc.py` compare `part_to_machine_point` à
`xyzacKinematicsInverse`, avec la correspondance de broches **lue dans le HAL
que le générateur produit** :

| Étage | Contre quoi | Poses | Écart max |
|---|---|---|---|
| `formule` | une transcription de `trtfuncs.c` | 56 | **7,105·10⁻¹⁵ mm** |
| `source` | la fonction **compilée** depuis `trtfuncs.c` | 56 | **7,105·10⁻¹⁵ mm** |

Soit l'epsilon machine : **les deux implémentations calculent la même
fonction.** Et, pour mesurer ce qui était en jeu, la correspondance **d'avant
correction** donne sur les mêmes poses un écart de **10,286 mm**. Ce n'était
pas une subtilité numérique, c'était un centimètre sur la pièce.

## 7. Pourquoi deux étages, et pourquoi pas en pilotant l'interface

L'étage `formule` seul est un **miroir** : il compare mon modèle à ma lecture
de la source. Une erreur de transcription rendrait l'accord parfait et faux.

La première version de l'étage 2 lançait LinuxCNC, levait l'arrêt d'urgence,
passait en MDI et relisait les articulations. Elle n'a jamais abouti, et les
obstacles rencontrés valent d'être notés parce qu'aucun ne concernait la
cinématique :

- **mémoire partagée résiduelle.** `linuxcnc.stat()` lit un segment SysV. Une
  instance tuée sans nettoyage laisse le segment vivant, **figé** — et `stat()`
  rend alors instantanément `joints=5, task_state=1` pour une instance qui n'a
  pas encore démarré. J'ai accusé mon code d'un défaut qui était un cadavre.
  Le signe révélateur est celui de tout ce projet : **une grandeur disponible
  avant que ce qui la produit existe.**
- **le symétrique** : sans instance, NML ne refuse pas, il *crée* le tampon,
  vide. Construire `stat()` trop tôt donne des zéros indéfiniment. Corriger la
  première faute a donc *révélé* la seconde : les deux se couvraient.
- **un garde-fou qui se déclenche sur lui-même** : cherchant `milltask` dans
  les lignes de commande, il a refusé de démarrer en signalant une instance
  vivante qui était sa propre invocation.

Or ce que l'étage 2 devait établir est précis : **la fidélité de la
transcription.** Compiler `trtfuncs.c` (quatre bouchons HAL suffisent :
`hal_malloc`, `hal_pin_float_newf`, `rtapi_print`, `rtapi_print_msg`) et
appeler sa fonction l'établit directement — sans arrêt d'urgence, sans prise
d'origine, sans NML. Toute la difficulté du pilotage était **accidentelle au
regard de la question posée**.

Le banc confirme au passage les sept noms de broches, identiques à ceux lus
sur l'instance vivante en §3.1.

## 8. Défaut n° 39, resté OUVERT : la configuration ne se met pas en marche

**Ce qui est établi.** `STATE_ESTOP_RESET` puis `STATE_ON` laissent
`task_state = 1` (ESTOP) et `motion.motion-enabled = FALSE`. La boucle
d'arrêt d'urgence fonctionne pourtant : `iocontrol.0.user-enable-out` passe de
FALSE à TRUE et `emc-enable-in` suit. Le statut lu n'est donc pas périmé — la
machine est réellement à l'arrêt.

**Le contrôle qui l'attribue.** La configuration de référence livrée avec
LinuxCNC (`configs/sim/gmoccapy/gmoccapy_XYZAC.ini`), passée par la **même**
séquence dans le **même** environnement, donne `task_state = 4` et
`motion.motion-enabled = TRUE`. Le défaut est donc dans ma configuration, pas
dans la méthode ni dans l'environnement.

**Ce qui a été écarté** : le câblage HAL de l'arrêt d'urgence, identique au mot
près à celui de toutes les configurations de simulation livrées ;
`[EMCIO]EMCIO = io`, qui a une valeur par défaut dans le script de démarrage ;
`FERROR`/`MIN_FERROR`, ajoutés sans effet.

**Ce que cela veut dire.** Une configuration qui démarre mais qu'on ne peut pas
mettre en marche est **inutilisable** : aucune ligne de G-code ne peut y être
exécutée. Et cela souligne la faiblesse de l'affirmation de la partie I : j'y
ai validé le **démarrage** et écrit « la configuration démarre », ce qui était
vrai — mais j'ai laissé entendre plus que cela. Démarrer n'est pas
fonctionner.

`FERROR` et `MIN_FERROR` ont été conservés (ils étaient absents et la référence
les porte), et le contradictoire commentaire « prise d'origine NON
renseignée » posé sous `HOME`/`HOME_SEQUENCE` a été corrigé — quarantième
défaut du projet, cinquième de la famille « une phrase fausse posée sur les
valeurs qu'elle prétend absentes ». La cause du refus de mise en marche reste
à trouver ; la bissection a été arrêtée après que l'état temps réel de
l'environnement est devenu peu fiable.

## 9. Ce qui reste non prouvé

- le **signe** des axes, qu'aucun calcul n'établit ;
- que le HAL porte les valeurs jusqu'aux broches **dans un système qui
  tourne** : établi une fois par `halcmd show pin xyzac` (§3.4), non
  automatisé ;
- la **mise en marche** (défaut n° 39) ;
- **±0,02 mm**, qui reste un objectif de qualification physique.
