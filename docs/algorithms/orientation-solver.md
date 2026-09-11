# Orientation Solver — algorithme détaillé

**Question posée.** L'accessibility solver dit ce qui est *possible* en chaque
point. Celui-ci choisit ce qu'on *fait*, sur toute la trajectoire, d'un seul
tenant.

---

## 1. Pourquoi une séquence et non un choix point par point

Trois raisons, et chacune suffirait :

1. **Double solution IK.** Chaque direction admet deux couples `(A, C)`.
   Le bon dépend du point précédent, pas du point courant.
2. **Retournement de plateau.** Deux points voisins peuvent avoir des ensembles
   admissibles voisins mais des optima locaux opposés. Une IK gloutonne produit
   alors un retournement `C` de 180° en pleine matière.
3. **Coût non local de la singularité.** Éviter `A → 0` demande parfois de
   dégrader plusieurs points *en amont*. Aucune décision locale ne peut le voir.

## 2. Méthode

```
1. candidats par point    K meilleures orientations admissibles (K = 24)
2. Viterbi                optimum GLOBAL sur l'ensemble discrétisé
3. segmentation 3+2       par intersection des ensembles admissibles
4. raffinement continu    local, chaque candidat re-vérifié en collision
```

Le choix de la **programmation dynamique** donne une propriété qu'on veut
pouvoir défendre : l'optimalité sur l'ensemble discret, et surtout le
**déterminisme**. Deux exécutions sur le même STEP produisent le même G-code.
Pour une machine, ce n'est pas un confort — c'est une condition de validation.
(Vérifié par `test_orientation_plan_is_deterministic`.)

## 3. Sélection des candidats

On garde les `K` orientations de **meilleur coût intrinsèque**, pas de meilleure
marge. Garder les 24 plus grandes marges concentrerait tous les candidats dans
un même coin de la sphère et priverait la DP de toute latitude pour assurer la
continuité.

## 4. Fonction de coût

### Coût de nœud (une orientation en un point)

| Terme | Poids | Justification physique |
|---|---|---|
| dégagement | 1,0 | `1 − min(marge, sat)/sat`, **saturé à 5 mm** : au-delà, une marge de plus n'apporte rien ; en deçà, elle pèse lourd |
| singularité | 8,0 | `severity(A)`, maximal en `A = 0`. Poids élevé : c'est un risque dynamique, pas une préférence |
| lead/tilt | 0,6 | écart à l'inclinaison technologique souhaitée |
| stabilité | 0,4 | `1 − d·n` : un axe rasant charge l'outil en flexion |

### Coût de transition

| Terme | Poids | Justification |
|---|---|---|
| continuité A | 0,35 | `(ΔA/10)²` |
| continuité C | 0,35 | `(ΔC/10)²`, sur `C` **déroulé** |
| course rotative | 0,05 | `(|ΔA| + |ΔC|)/10` : temps et usure |
| changement de branche | 6,0 | changer de branche IK en pleine passe est très coûteux |

**Contrainte dure** : `violates_rotary_rate` → coût infini. Sur une machine
table/table, une grande rotation sur un petit pas linéaire signifie que la pièce
balaie vite sous l'outil : l'avance au point de contact explose même si l'avance
programmée est modeste. C'est une contrainte, pas une pénalité.

### Déroulage de C

Avant tout calcul de `ΔC`, `C` est ramené au représentant le plus proche du
point précédent (`unwrap_towards`). Sans cela, une trajectoire traversant ±180°
paierait un coût de 358° pour un mouvement réel de 2°, et la DP choisirait de
l'éviter — c'est-à-dire de contourner un problème qui n'existe pas.

## 5. Viterbi

```
dp[0][t] = coût_nœud(0, t)
dp[i][t] = coût_nœud(i, t) + min over s de  dp[i−1][s] + coût_transition(s → t)
```

Complexité `O(P · K²)` avec `P` = points, `K` = candidats. Pour `P = 5000` et
`K = 24`, ≈ 2,9 M évaluations de transition — négligeable devant le calcul
d'accessibilité amont.

Si aucune transition n'est admissible en un point, on ne « rattrape » pas : le
plan est retourné **incomplet**, avec les indices fautifs. Une trajectoire
partiellement inaccessible n'est pas « presque bonne », et présenter une
solution dégradée sans le dire serait le pire comportement possible.

## 6. Segmentation 3+2 — la règle est *dérivée*, pas réglée

```
i ← 0
tant que i < P :
    inter ← admissibles(i)
    j ← i
    tant que j+1 < P et  inter ∩ admissibles(j+1) ≠ ∅ :
        inter ← inter ∩ admissibles(j+1)
        marge_segment ← min(marge_segment, marges(j+1))    # la PIRE marge
        j ← j+1
    si (j−i+1) ≥ min_run et inter ≠ ∅ :
        → segment 3+2, orientation = argmax(marge_segment − w·singularité)
    sinon :
        → segment simultané
    i ← j+1
```

**Le simultané n'est jamais un choix : c'est ce qui reste quand la géométrie
interdit toute orientation commune.** Cela réalise littéralement « 3+2 lorsque
possible, simultané uniquement lorsqu'utile », et le point de bascule est
affichable — donc explicable à l'utilisateur.

La marge d'un segment indexé est la **pire** marge sur le segment : une
orientation doit dégager en **tout** point, pas en moyenne.

`indexed_fraction` est un indicateur produit majeur : plus il est haut, plus la
gamme est rapide et rigide.

## 7. Raffinement continu

La DP donne l'optimum *sur la grille*, dont le pas vaut ~8,6°. Le raffinement va
chercher ce qui se trouve entre les nœuds, dans un cône de ±6° autour de la
solution, en trois anneaux.

**Chaque candidat raffiné est re-vérifié en collision.** Un raffinement qui
ferait confiance à l'interpolation réintroduirait exactement le risque que toute
l'architecture cherche à éliminer. Si le raffinement échoue, on garde la
solution DP, qui est valide.

## 8. Résultats observés sur le corpus

| Cas | Points | Accessibles | Couverture 3+2 | Lecture |
|---|---|---|---|---|
| C08 trou incliné, face plane | 24 | 24/24 | **100 %** | une orientation couvre toute la face — comportement attendu |
| C10 dôme, face plane latérale | 24 | 24/24 | **100 %** | idem |
| C10 dôme, face sphérique, hémisphérique | 30 | 23/30 | 0 % | normales variant sur 90° : aucune orientation commune, simultané justifié ; 7 points bloqués par la tige en pied de dôme |
| C06 contre-dépouille | 28 | 27/28 | — | plan incomplet signalé, point bloquant nommé |

Le cas du dôme est celui qui valide la règle : l'intersection des ensembles
admissibles **se vide**, et le moteur bascule en simultané sans qu'on le lui ait
demandé.

## 9. Vérification exacte de l'orientation indexée (M2)

Les **germes analytiques** ajoutés en M2 à l'accessibility solver ne sont pas
des sommets de grille : ils sont rattachés au sommet le plus proche. Or
l'intersection d'ensembles du §6 travaille sur des indices de grille.

Elle est donc devenue une **heuristique de proposition** — exacte sur les
sommets de grille, approchée sur les germes. Sans garde-fou, un segment pourrait
être déclaré indexable sur une orientation qui ne dégage pas partout : le seul
type d'erreur que ce projet ne peut pas se permettre.

`segment_3plus2` accepte donc un `verify(index, direction) -> (ok, marge)` et
**re-teste l'orientation proposée en chaque point du segment**. Les 8 meilleures
candidates sont essayées dans l'ordre : se limiter à la meilleure ferait
basculer tout le segment en simultané dès qu'elle échoue, alors qu'une voisine
convient souvent. Si aucune ne passe, le segment devient simultané — jamais
indexé sur une orientation non vérifiée.

## 10. Raffinement : la vérification doit connaître la MACHINE (M2)

Le raffinement est désormais câblé. La première version de son vérificateur ne
testait que la pièce, et la mesure a été instructive : libre d'optimiser le
dégagement sans contrainte machine, le raffinement a gagné 0,24 mm de marge en
poussant l'axe Z à **60,1 mm pour une course qui s'arrête à 60,0**. Un plan
meilleur sur le critère optimisé, et irréalisable.

`make_pose_verifier` (module `simulation_engine`) est donc le point unique de
construction de cette fonction, partagé par la segmentation 3+2 et le
raffinement. Elle vérifie les deux : ce que l'outil rencontre, et ce que la
machine peut atteindre.

### Le score du raffinement doit porter sur la course RÉELLE des axes

Deuxième mesure instructive, même famille d'erreur : le score ne pénalisait que
l'écart angulaire entre directions voisines — un proxy géométrique du lissage.
Résultat : +0,26 mm de marge gagnés en faisant passer la course A+C de **86 à
145°**.

Deux directions peuvent être très proches sur la sphère et demander des couples
(A, C) très éloignés. C'est la difficulté propre à la cinématique AC, et aucun
critère purement géométrique ne la voit. Le score porte donc désormais sur
`|ΔA| + |ΔC|` calculé par cinématique inverse, avec `C` déroulé.

Effet mesuré sur C02 face #2, hémisphérique :

| | marge min | course A+C |
|---|---|---|
| plan DP | 0,369 mm | 85,7° |
| raffiné, score géométrique seul | 0,624 mm | **144,7°** |
| raffiné, score avec course réelle | 0,542 mm | **94,9°** |

Le compromis est maintenant explicite et piloté par `OrientationWeights.rotary_travel`.

## 11. Limites connues

- ~~Raffinement non câblé~~ → **levé en M2**.
- ~~Pas de collision sur le balayage~~ → **levé en M2** : voir
  `collision_engine/sweep.py` et la verification V4 du `TrajectoryValidator`.
- Les poids par défaut n'ont **pas** été calibrés sur machine réelle. Ce sont
  des points de départ raisonnés, pas des valeurs qualifiées. Cette limite
  **exige une machine** et ne peut pas être levée par le calcul.
- Pas de gestion des mouvements de dégagement entre cônes d'accessibilité
  disjoints : quand l'orientation doit sauter d'un cône à l'autre, le solveur
  paie le coût de transition mais ne planifie pas de retrait.
- La DP optimise sur l'ensemble discret des candidats retenus (K = 24) ;
  l'élagage par coût intrinsèque est une heuristique, pas une garantie.
