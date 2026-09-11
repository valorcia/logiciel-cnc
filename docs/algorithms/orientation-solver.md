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

## 9. Limites connues

- Le raffinement continu n'est pas encore appelé par le prototype : il demande
  un `collision_check` fourni par l'appelant, câblé en M2.
- Les poids par défaut n'ont **pas** été calibrés sur machine réelle. Ce sont
  des points de départ raisonnés, pas des valeurs qualifiées.
- Pas encore de vérification de collision sur le mouvement **entre** deux points
  (balayage) : on vérifie les positions, pas les transitions. Prérequis du
  `simulation_engine` M2. **Tant que ce n'est pas fait, aucune trajectoire ne
  peut être considérée comme validée**, et c'est l'une des raisons du verrou
  ADR-001 §6.
- Pas de gestion des mouvements de dégagement entre cônes d'accessibilité
  disjoints.
