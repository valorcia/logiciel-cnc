# ADR-010 — Jalon M10 : décider une passe de finition **complète**

## 1. Ce que M10 lève, et ce qu'il ne lève pas

La finition était planifiée sur un **préfixe contigu** de chaque passe, faute de
pouvoir en payer la totalité : un point de contact coûte 65 ms en résolution
complète, et une gamme de finition du dôme C10 compte **159 899 points**, soit
près de trois heures. Le plan était une maquette — et, bien pire, le **mode
qu'elle annonçait était celui du préfixe**.

Ce n'était pas une imprécision mais une conséquence nécessaire de la règle du
moteur : le mode sort de l'**intersection** des ensembles admissibles, et une
intersection ne peut que rétrécir quand on ajoute des points. Un préfixe donne
donc systématiquement un mode **optimiste**.

**Levé.** Le verdict 3+2 porte désormais sur la passe entière. La gamme
complète du dôme est décidée en **208 s** — contre 1 091 s pour 18 % de
couverture auparavant.

**Non levé.** La trajectoire **simultanée**. Elle demande le champ admissible
complet en chaque point et reste à trois heures. Ce jalon rend décidable le
3+2, positivement comme négativement ; quand la réponse est « pas en 3+2 », il
le dit **sans pouvoir proposer l'alternative**, et aucune opération n'est émise.

---

## 2. Décisions

### D86 — Explorer et vérifier ne coûtent pas la même chose

`solve_point` teste 642 directions filtrées pour **découvrir** ce qui est
possible : 65 ms. Vérifier **une** orientation déjà connue demande un seul test
exact, vectorisable sur les points : **1,6 ms**. Facteur 40.

D'où une décision en deux temps :

1. **sondage** — résolution complète en quelques points. Leur intersection
   donne des **candidats**. Hypothèse, jamais conclusion.
2. **vérification** — chaque candidat testé en **chaque** point de la passe.

Ce n'est pas une optimisation ajoutée après coup : c'est la reconnaissance que
la question « quelles orientations existent ? » et la question « celle-ci
tient-elle partout ? » n'ont pas le même coût, et que le moteur ne posait que
la première.

### D87 — La taille de bloc est un réglage de coût, jamais de verdict

Le préfiltre d'obstacles de `check_many` se rabat sur une sphère de rayon
« portée + étendue du bloc ». Un bloc large le rend inopérant :

| bloc | coût | | bloc | coût |
|---|---|---|---|---|
| 8 | 1,92 ms/pt | | 128 | 11,79 ms/pt |
| 16 | **1,60 ms/pt** | | 256 | 25,93 ms/pt |
| 32 | 1,84 ms/pt | | 512 | 29,65 ms/pt |

À 256, la vérification est **aussi lente que le champ complet** — et c'est la
valeur qu'avait le premier prototype, ce qui l'a fait conclure à tort que
l'approche n'apportait rien. Le nombre de points dégagés est **identique** à
toutes les tailles (2 630 sur 3 000), et un test l'exige : la taille de bloc ne
doit jamais pouvoir devenir un réglage de résultat.

### D88 — Les points de sondage sont **répartis**, à l'inverse de la maquette

Le préfixe contigu de la maquette était le bon choix pour elle : il préserve la
continuité du chemin, et un `linspace` sur 245 917 points donnait des points
distants de 1 640 rangs — une suite de sauts, pas une passe, que l'orientation
solver payait 13 000 deg de course A+C.

Pour le sondage, le critère est inverse : on veut faire **rétrécir
l'intersection le plus vite possible**, donc des points dissemblables. Les deux
choix sont justes pour leur usage ; les confondre donnerait soit une
intersection trop large, soit une trajectoire qui n'existe pas.

### D89 — On retient le candidat au plus grand dégagement **minimal**

Pas le premier qui passe. Mesure sur les parois du dôme C10 : le premier
candidat donne 12,0 mm de dégagement, le meilleur des six **16,1 mm**. Prendre
le premier serait accepter 25 % de dégagement en moins sans raison.

### D90 — La marge tous tronçons confondus ne veut rien dire

Le minimum sur **tous** les tronçons est dominé par l'arête de coupe, tangente
à la surface **par construction** — puisque c'est elle qui coupe. Mesure sur
les parois du dôme : marge tous tronçons **0,0004 à 0,007 mm**, dégagement des
tronçons **non coupants 14 à 16 mm**. Quatre ordres de grandeur.

C'est exactement le défaut qui rendait le certificat de gouge du jalon M6 vide
de contenu, et il s'est reproduit ici. Le rapport annonce donc le dégagement
hors coupe, et `min_margin` porte dans sa documentation la raison de sa propre
inutilité.

### D91 — Le positif s'établit par exemple, le négatif par épuisement

Les trois verdicts portent sur la passe entière, mais pas au même titre :

* **`verification`** — conclusion pleine. Une orientation est exhibée et testée
  exactement en chaque point.
* **`contre-exemple`** — un point qu'aucune orientation n'atteint conclut sur
  toute la passe, et pas seulement contre le 3+2 : aucune trajectoire, même
  simultanée, n'y passera.
* **`intersection-vide`** — une intersection calculée sur un sous-ensemble
  **contient** celle de l'ensemble : vide sur 24 points implique vide sur
  73 792.

Mais les deux négatifs épuisent une **grille** de 642 directions (8,6 deg à
`subdivisions=3`). Qu'aucune ne dégage n'interdit pas formellement qu'une
direction intermédiaire le fasse. La réserve est **énoncée** dans
`IndexedPassVerdict.conclusive` plutôt que passée sous silence, et elle est
structurelle : un épuisement sur un ensemble discret n'est qu'un épuisement sur
cet ensemble.

### D92 — Aucune opération n'est émise pour une passe non indexable

Émettre une opération « simultané » laisserait croire qu'une trajectoire a été
calculée. Elle ne l'a pas été, et ce jalon ne la rend pas abordable. Le rapport
porte le verdict, le plan ne porte rien.

### D93 — Le montage du banc est **dérivé de la pièce**

Voir §3, défaut n° 41. Le rehausseur vaut 25 mm, et le critère de ce choix
n'est pas « le plus de dégagement possible » mais **« n'introduire aucune
limite nouvelle »** :

| rehausseur | parois verticales | dôme |
|---|---|---|
| 10 mm | 2 inatteignables, 2 à 99,6 % | `COLLISION_CUTTING` |
| **25 mm** | **4 en 3+2**, dégagement 12,7–14,1 mm | `COLLISION_CUTTING` |
| 40 mm | 4 en 3+2, dégagement 14,4–16,8 mm | `COLLISION_CUTTING` |
| 60 mm | 4 en 3+2 | **`MACHINE_TRAVEL`** |

À 60 mm la course linéaire se met à buter et **masque la vraie cause** du rejet
sur le dôme, qui est que l'arête de coupe ne rentre pas dans le rayon local.
Monter plus haut achète du dégagement au prix d'un diagnostic faux.

---

## 3. Les défauts trouvés

### 41 — Un montage de banc fixe rendait des faces « inaccessibles »

`BenchState` posait la pièce à `(0, 0, 25)`. Le dôme C10 a son repère au coin
et mesure 60 × 60 mm : la pièce était donc **à cheval sur le bord du plateau**.
Deux des quatre parois verticales étaient déclarées inatteignables et deux
accessibles — **une asymétrie sans aucune cause géométrique**. Centrée et
rehaussée, les quatre parois offrent 35 à 38 orientations admissibles.

C'est la troisième fois que ce banc fait paraître la machine incapable par un
réglage par défaut (V1 : fraise à bout droit, 2 orientations contre 106 ; V1 :
singularité rejetée). Le montage est maintenant **dérivé de la boîte de la
pièce** et le banc le dit dans ses messages.

**Et ma propre mesure de sensibilité était aveugle.** J'avais fait varier la
hauteur de montage de 25 à 120 mm en concluant « insensible, ce n'est pas
ça » — parce que je n'avais regardé que les quatre plus **grandes** passes, qui
butent sur autre chose. Les quatre parois, elles, basculaient. Faire varier le
paramètre ne suffit pas : **il faut aussi mesurer la bonne grandeur.**

### 42 — Le rapport sous-estimait son propre résultat

`FinishingOpReport.describe()` annonçait « MAQUETTE : 0,2 % de la passe — le
mode annoncé ne vaut que pour ce segment » pour un verdict **définitif**. Le
champ `coverage` confondait deux choses distinctes : la part des points
**examinés** et la portée de la **conclusion**. D'où `basis` et `conclusive`.

Une phrase trop prudente est fausse comme une phrase trop affirmative.

### 43 — La marge vide de contenu, revenue de M6

Voir D90. Quatre ordres de grandeur entre la grandeur affichée et la grandeur
utile.

---

## 4. Ce que la vérification complète change, en un chiffre

À un rehausseur de 10 mm, deux parois verticales rendent le verdict
**« pas-3+2, le meilleur candidat couvre 99,6 % »** : une douzaine de points
sur 3 213 ne dégagent pas.

Un préfixe de 400 ou de 4 000 points les aurait presque sûrement manqués et
aurait annoncé **3+2**. Ce n'est donc pas une amélioration de précision : c'est
la différence entre un plan juste et un plan faux, sur une passe que rien ne
distinguait des autres.

---

## 5. État après M10

| | |
|---|---|
| Gamme de finition du dôme C10 | **décidée en 208 s**, 159 899 points, verdict sur chaque passe |
| Passes prouvées 3+2 | 4 sur 8, vérifiées en chacun de leurs points, dégagement 12,7–14,1 mm |
| Passes rejetées | 4 sur 8, définitivement, avec le motif et le remède nommés |
| Trajectoire simultanée | **toujours hors de portée** (trois heures) |
| Performance sur Pi 5 | **toujours jamais mesurée** |
| ±0,02 mm | objectif de qualification physique, inchangé |
