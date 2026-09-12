# Mesurer la performance, ici et sur le Raspberry Pi 5

## 1. Ce que ce dossier règle, et ce qu'il ne règle pas

Depuis le jalon M6 la documentation répète : **« jamais mesuré sur Pi 5 :
l'extrapolation ×3–5 reste une extrapolation »**. C'était honnête et
improductif : la phrase se répétait de jalon en jalon sans jamais se
rapprocher d'un chiffre.

`tools/bench_platform.py` ne supprime pas ce manque, il le rend
**franchissable** : il produit exactement les mêmes mesures sur deux machines,
de sorte que le rapport soit **mesuré et non deviné**. Aucun chiffre
d'extrapolation n'apparaît nulle part dans cet outil.

**Ce qui n'est toujours pas fait : la mesure sur Pi 5.** L'environnement de
développement est x86_64, et une mesure de performance sous émulation
n'aurait aucune valeur. La procédure et la référence existent ; le verdict
viendra de la machine de l'utilisateur.

## 2. Le prérequis dur, vérifié

`cadquery-ocp` — la dépendance lourde du projet, OCCT 8.0.1 — publie bien une
roue aarch64 pour la version employée :

```
cadquery_ocp-8.0.1.0.0-cp311-cp311-manylinux_2_28_aarch64.whl
```

`manylinux_2_28` exige glibc ≥ 2.28 ; Raspberry Pi OS Bookworm (Debian 12)
fournit glibc 2.36, Bullseye 2.31. Donc `pip install` suffit, sans
compilation d'OCCT.

*Note de méthode :* une première vérification par `pip download --platform
manylinux_2_35_aarch64` a échoué et semblait démontrer l'absence de roue.
L'étiquette était simplement fausse — la roue est en `manylinux_2_28`. Un
échec d'outillage n'est pas un verdict d'indisponibilité, et c'est la
deuxième fois dans ce projet.

## 3. Où passe le temps, et pourquoi cela décide du rapport

Profilage de la boucle chaude — vérification d'une orientation sur 1 500
points, x86_64 :

| | part | appels |
|---|---|---|
| `signed_clearance_to_segment` | 36 % | 1 222 |
| corps de `check_many` | 36 % | 282 |
| réductions numpy (`ufunc.reduce`) | 12 % | 7 334 |
| `subset_near` | 6 % | 282 |

Tailles **réelles**, mesurées et non supposées :

* champ d'obstacles passé à `check_many` : 34 146 points ;
* après préfiltre sphérique : **1 980** (médiane sur 282 appels) ;
* lignes retenues par la bande par coquille : **691** (médiane), 1 368 en
  moyenne, 27 à 8 038 ;
* tronçons évalués : **4,3 sur 13**.

Les deux préfiltres fonctionnent donc, et le travail porte sur des tableaux
de ~691 × 16 à 1 980 × 16 float64 — **88 à 256 ko, résidents en cache L2**.
Ce n'est pas un régime limité par la bande passante DDR, et le rapport entre
deux machines dépendra du **débit SIMD** et du coût d'appel de numpy. Le
triade mémoire est mesuré à part précisément pour qu'on puisse vérifier cette
lecture sur la machine cible plutôt que la croire.

*Deux erreurs de mesure commises en chemin, toutes deux du même genre :*
j'ai d'abord mesuré les micro-noyaux à N = 34 146 (la taille **avant**
préfiltre) puis le noyau géométrique à N = 1 980 (la taille avant la bande
par coquille). Les deux surestimaient — d'un facteur 17 et 3,5. **Mesurer une
taille qui n'existe pas donne un chiffre exact et faux.**

## 4. La référence x86_64

`docs/bench/x86_64.json`. Machine : Intel Xeon @ 2,80 GHz, 4 cœurs, 16 Go,
NumPy 2.4.6 sur scipy-openblas.

| micro-noyau | µs |
|---|---|
| `signed_clearance_to_segment` 691 × 16 | 691 |
| idem 1 368 × 16 | 1 485 |
| `z_all` 1 980 × 16 | 320 |
| `d2` 1 980 × 16 | 451 |
| `r_all` 1 980 × 16 | 273 |
| `min(axis=0)` | 78 |
| surcoût d'un appel numpy | 3,5 |
| triade mémoire 4 Mo | 23,2 Go/s |
| triade mémoire 64 Mo | 7,3 Go/s |

| chaîne réelle (dôme C10) | |
|---|---|
| import STEP | 0,02 s |
| champ d'obstacles (34 146 points) | 0,71 s |
| échantillonnage surface (1 239 974 points) | 4,39 s |
| génération des 8 passes (159 899 points) | 1,87 s |
| `solve_point` — **explorer** | **75,1 ms/point** |
| `verify_direction` — **conclure** | **1,53 ms/point** |
| verdict vérifié sur une passe de 3 213 points | 17,3 s |
| pic mémoire | **789 Mo** |

**La mémoire n'est pas le facteur limitant.** 789 Mo de pic pour la décision
complète, dont 273 Mo d'imports OCCT et un pic transitoire de tessellation ;
les tableaux retenus ne font que 59 Mo. Un Pi 5 de 4 Go suffit, et cette
mesure-là transfère telle quelle puisque les structures sont les mêmes.

## 5. La procédure sur le Pi 5

```bash
# Raspberry Pi OS Bookworm 64 bits
sudo apt install -y python3-dev python3-venv build-essential
python3 -m venv ~/venv && . ~/venv/bin/activate
git clone <ce depot> && cd logiciel-cnc
pip install -e ".[dev]"          # roue aarch64, pas de compilation OCCT
python tools/make_corpus.py      # 20 geometries STEP

python tools/bench_platform.py --compare docs/bench/x86_64.json \
                               --json docs/bench/pi5.json
```

Le banc calibre lui-même son nombre de répétitions, donc il ne devient pas
interminable sur une machine lente.

**Ce qu'il faudra regarder dans le résultat**, et ce que chaque cas voudrait
dire :

* un rapport **proche de 1 sur le triade mémoire** et **plus grand sur les
  micro-noyaux** confirmerait la lecture du §3 — régime SIMD et coût d'appel,
  pas bande passante ;
* l'inverse la réfuterait, et l'optimisation devrait alors viser le nombre de
  passes sur les tableaux, non le nombre d'appels ;
* `verify_ms_par_point` est la ligne qui tranche : c'est elle qui fixe si une
  gamme de finition se décide en minutes ou en heures sur la machine cible.

## 6. Ce que le résultat ne dira pas

Rien sur le **temps réel** de LinuxCNC : ce banc mesure la planification, qui
tourne hors ligne. La boucle d'asservissement est un autre sujet, et elle ne
partage aucun code avec ce qui est mesuré ici.
