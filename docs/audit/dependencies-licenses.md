# Audit des dépendances et licences — jalon M0

Date : 2026-09-11. Vérifications faites **sur cet environnement** (pip, métadonnées de paquets) et
sur les dépôts amont. Tout ce qui n'a pas été vérifié est marqué **[NON VÉRIFIÉ]**.

Hypothèse de distribution retenue pour l'analyse : le logiciel est **distribué** avec un kit vendu
(image Raspberry Pi + paquets). C'est la distribution qui déclenche les obligations copyleft ;
une hypothèse « usage interne seulement » changerait les conclusions et n'est donc pas retenue.

---

## 1. Tableau de synthèse

| Composant | Version | Licence | Vérifié comment | Verdict |
|---|---|---|---|---|
| **cadquery-ocp** (OCP → OCCT) | 8.0.1.0.0 | Apache-2.0 (bindings) **+ OCCT LGPL-2.1 + exception OCC** (binaires embarqués) | `importlib.metadata` local + doc amont | ✅ Retenu — noyau |
| **OCCT** (embarqué) | 8.0.1 | LGPL-2.1 + Open CASCADE Exception 1.0 | doc amont OCC / SPDX | ✅ Liaison dynamique OK |
| **NumPy** | 2.4.6 | BSD-3-Clause | amont | ✅ |
| **SciPy** | 1.17.1 | BSD-3-Clause (bundle OpenBLAS BSD-3) | métadonnées locales | ✅ |
| **trimesh** | installé | MIT | amont | ✅ utilitaire maillage |
| **networkx** | installé | BSD-3-Clause | amont | ✅ graphes (DP, features) |
| **matplotlib** | installé | PSF-like (BSD-compatible) | amont | ✅ rendu hors-ligne |
| **pydantic** | 2.13.5 | MIT | métadonnées locales | ✅ modèles de données |
| **pytest** | installé | MIT | amont | ✅ tests |
| **OpenCAMLib** | 2023.1.11 (PyPI) | **LGPL-2.1** (depuis 08/2018) | dépôt `aewallin/opencamlib` | ⚠️ Adapter optionnel, hors paquet cœur |
| **FreeCAD / CAM (ex-Path)** | 1.x | **LGPL-2+** | amont | ⚠️ Backend de comparaison hors ligne |
| **OpenCV** | — | Apache-2.0 (≥ 4.5.0) | amont | ✅ vision |
| **Ultralytics YOLO** | — | **AGPL-3.0** | dépôt + page licence éditeur | ❌ **Exclu du paquet distribué** |
| **LinuxCNC** | 2.9+ | **GPLv2** (+ LGPLv2.1 pour partie) | amont | ⚠️ Frontière de **processus** obligatoire |
| **CurviSlicer** | master | **AGPL-3.0** | dépôt `mfx-inria/curvislicer` | ❌ Étude conceptuelle seule |
| **OrcaSlicer** | — | **AGPL-3.0** | dépôt `OrcaSlicer/OrcaSlicer` | ❌ Étude UX seule |
| **PrusaSlicer** | — | **AGPL-3.0** | amont | ❌ Étude UX seule |
| **S³-Slicer** (`S3_DeformFDM`) | — | BSD-3-Clause | dépôt `zhangty019/S3_DeformFDM` | ℹ️ Licence OK, **portée additive** |
| **Open5x** | — | MIT | dépôt `FreddieHong19/Open5x` | ℹ️ Licence OK, **dépend de Rhino/Grasshopper** |

---

## 2. Vérifications faites ici, avec leur résultat brut

### 2.1 Noyau B-Rep : le point qui a tranché D1

```
$ pip3 index versions pythonocc-core
ERROR: No matching distribution found for pythonocc-core

$ pip3 download --no-deps cadquery-ocp
Saved cadquery_ocp-8.0.1.0.0-cp311-cp311-manylinux_2_28_x86_64.whl      (66.9 MB)

$ pip3 download --no-deps --platform manylinux_2_28_aarch64 --python-version 311 cadquery-ocp
Saved cadquery_ocp-8.0.1.0.0-cp311-cp311-manylinux_2_28_aarch64.whl     (61.6 MB)

$ python3 -c "from OCP.STEPControl import STEPControl_Reader; print('OCP import OK')"
OCP import OK
```

**Lecture** : `pythonocc-core` n'existe pas sur PyPI (distribution conda). `cadquery-ocp` existe pour
x86_64 **et aarch64**. Comme la cible embarquée est un Pi 5 (aarch64), c'est l'argument décisif :
le même `pip install` fonctionne sur le poste de l'utilisateur et sur la machine.

### 2.2 Nuance de licence sur `cadquery-ocp` — à ne pas simplifier

Les métadonnées du wheel déclarent :

```
cadquery-ocp  8.0.1.0.0  License='Apache-2.0'
```

**Cette déclaration ne couvre que le code de binding pybind11.** Le wheel **embarque les bibliothèques
partagées OCCT**, qui restent sous **LGPL-2.1 + Open CASCADE Exception 1.0**. Conclure « Apache-2.0 »
à partir de la métadonnée seule serait une erreur d'audit.

**Obligations qui en découlent, à tenir même en produit propriétaire** :
1. liaison **dynamique** à OCCT (c'est le cas : `.so` embarqués, chargés au runtime) ;
2. mention de licence + accès au source OCCT pour les destinataires ;
3. l'utilisateur doit pouvoir **remplacer** la version d'OCCT (ne pas geler les `.so` dans un binaire
   statique, ne pas empêcher le relink).

Ces trois points doivent figurer dans le `NOTICE` de l'image Pi. **Action ouverte : rédiger `NOTICE`.**

---

## 3. Les trois risques de licence réels

### R-LIC-1 — Ultralytics YOLO (AGPL-3.0) : risque produit direct ❌

La demande initiale mentionne « backend YOLO interchangeable ». Le problème n'est pas technique.

L'AGPL-3.0 impose de publier le source de l'œuvre dérivée, y compris pour un accès **réseau**. Or :
- le produit est **vendu** avec le kit ;
- l'UI est prévue comme un service accessible en réseau local (le Pi sert l'interface) — ce qui
  active précisément la clause réseau de l'AGPL, celle qui la distingue de la GPL ;
- l'éditeur soutient publiquement qu'un usage commercial, **même en R&D interne**, requiert une
  licence Enterprise.

Que l'on partage ou non l'interprétation extensive de l'éditeur, le risque juridique est réel et
n'a pas à être couru pour un composant **remplaçable**.

**Décision appliquée** : `vision_service` définit `Detector` comme interface. Le backend livré cible
ONNX Runtime (MIT) + modèle sous licence permissive. Un backend Ultralytics reste possible **en
plugin tiers hors dépôt**, installé volontairement par l'utilisateur final — auquel cas
l'obligation lui incombe, et non à nous.

### R-LIC-2 — LinuxCNC (GPLv2) : frontière de processus obligatoire ⚠️

`import linuxcnc` dans notre processus Python crée un lien avec du code GPLv2 et pose la question de
l'œuvre dérivée pour l'ensemble de l'application.

**Décision appliquée** : `linuxcnc_gateway` communique **par processus séparé et protocole texte**
(`linuxcncrsh` / socket / fichiers G-code déposés), jamais par liaison en processus. L'échange est
du **G-code et de l'état**, c'est-à-dire des données, pas des appels de fonction.

Bénéfice secondaire non négligeable : cette frontière est aussi une frontière de **sûreté**
(D9). La contrainte de licence et la contrainte de sécurité poussent ici dans le même sens, ce qui
est un bon signe pour l'architecture.

### R-LIC-3 — Contamination par inspiration ⚠️

CurviSlicer, OrcaSlicer et PrusaSlicer sont **tous AGPL-3.0**. Le risque n'est pas de copier un
fichier — c'est de copier une structure de données ou une séquence d'algorithme en les
retranscrivant.

**Règle de travail** : pour ces trois projets, on lit la **publication** et on observe l'**UI**.
On ne lit pas le code source pour en dériver une implémentation. Toute PR qui cite un fichier source
AGPL comme référence d'implémentation est refusée.

---

## 4. Ce qui est réutilisable, et ce qui ne l'est pas

| Projet | Réutilisable ? | Ce qu'on en prend |
|---|---|---|
| OpenCAMLib | **Oui** (LGPL-2.1, adapter) | Drop-cutter et waterline pour les segments **3+2 indexés**. Aucune notion 5 axes ni porte-outil : ne résout pas notre problème, mais résout bien le sien. |
| FreeCAD CAM | **Techniquement** (LGPL-2+) | Banc de comparaison hors ligne + corpus de post-processeurs comme référence de format. Pas embarqué. |
| S³-Slicer | Licence oui (BSD-3) | **Additif.** Déformation/champ scalaire pour trouver des directions d'impression. Concept transposable à l'orientation, **code non transposable** (Windows + VS + QT + oneMKL). |
| Open5x | Licence oui (MIT) | **Le slicing dépend de Rhino/Grasshopper (propriétaire).** Donc : référence matérielle et preuve de faisabilité 5 axes accessible, pas une brique logicielle. |
| CurviSlicer | **Non** (AGPL) | Idée : la couche n'a pas à être plane. 3 axes, additif, dépend de TetWild et d'un QP. |
| Orca/Prusa | **Non** (AGPL) | UX : gestion de profils, prévisualisation, mode expert. |

**Le point important de cet audit** : aucun des projets « multi-axes » cités dans la littérature ne
fournit un moteur réutilisable pour notre problème. Ils sont soit **additifs** (S³-Slicer, Open5x,
CurviSlicer), soit **3 axes** (OCL, CurviSlicer), soit **dépendants d'un CAO propriétaire** (Open5x).

La conséquence est directe et il faut l'énoncer sans détour : **l'accessibility solver et
l'orientation solver avec outil complet doivent être écrits par nous**. C'est cohérent avec le fait
que ce soit le différenciateur produit — mais cela veut dire qu'aucun raccourci n'existe, et que
l'effort de R&D est à provisionner en conséquence.

---

## 5. Actions ouvertes

| ID | Action | Bloquant pour |
|---|---|---|
| A-LIC-1 | ADR-002 : licence du produit | Distribution |
| A-LIC-2 | Rédiger `NOTICE` (OCCT LGPL + attributions) | Distribution |
| A-LIC-3 | Choisir le modèle de détection permissif + le figer | `vision_service` |
| A-LIC-4 | CI : refus de merge si une dépendance AGPL/GPL entre dans le paquet cœur | Continu |
| A-LIC-5 | Vérifier la licence des **profils** d'outils/matières importés | `recipe_profiles` |
