# ADR-002 — Jalon M2 : lever les limites bloquantes de M1

- **Statut** : Accepté (jalon M2)
- **Date** : 2026-09-11
- **Contexte** : complète ADR-001, ne le remplace pas.

> **Note** : ADR-001 / D10 réservait le numéro ADR-002 à la décision de licence
> produit. Celle-ci reste **non tranchée** ; elle est reportée à ADR-003 pour ne
> pas bloquer le travail technique sur une décision commerciale.

---

## 1. Les limites déclarées à M1, et ce qui en a été fait

| # | Limite M1 | Traitement M2 | État |
|---|---|---|---|
| 1 | 122 ms/point, extrapolé 350–600 ms sur Pi 5 | bande radiale par tronçon + index spatial adaptatif | **55 ms/point** (×2,2) ; ×48 sur grande pièce |
| 2 | Volumes machine absents du champ d'obstacles | `MachineGuard`, testé dans le repère machine | **levée** |
| 3 | **Aucune collision sur le balayage** (bloquant) | `SweepChecker`, subdivision sur borne prouvée | **levée** |
| 4 | Brut traité comme intact | `MaterialState` voxel + suivi d'enlèvement | **levée** |
| 5 | Gouge fine hors de portée du nuage | `verify_gouge_exact` (B-Rep, `BRepExtrema`) | **partielle** : sondage épars |
| 6 | Raffinement continu non câblé | câblé, avec vérificateur machine-aware | **levée** |
| 7 | Poids non calibrés | — | **ouverte** (exige une machine) |
| 8 | Bridages STEP non échantillonnés | `Fixture.step_path` supporté | **levée** |

---

## 2. Décisions

### D12 — Le goulot de performance était le nombre d'obstacles, pas la boucle

**Mesure d'abord.** M1 avait montré que boucle et version vectorisée étaient à
10 % l'une de l'autre : la structure de boucle n'était donc pas en cause.

La vraie observation : `|p − tcp|` **ne dépend pas de la direction testée**
(à `spread` près). Or un point ne peut atteindre le tronçon `[z₀,z₁]×[r₀,r₁]`
que si

```
z₀ − inf − spread  ≤  |p − tcp|  ≤  √((z₁+inf)² + (r_max+inf)²) + spread
```

puisque `|p − tcp|² = z² + r²`. Chaque tronçon ne voit donc qu'une **coquille**
du nuage, calculée **une fois** pour toutes les orientations.

L'effet est très inégal selon le tronçon, et c'est tout l'intérêt : l'arête de
coupe (z ≤ 20 mm, r = 3 mm) ne voit qu'une petite boule, alors qu'elle balayait
auparavant les mêmes milliers de points que le nez de broche.

**Rejeté** : le passage en `float32` (gain attendu marginal une fois la coquille
en place, et perte de précision sur des marges au centième).

### D13 — L'index spatial est **adaptatif**, sur un critère mesurable

Première mesure : ×1,5 seulement. Diagnostic : dans une scène où la pièce est
plus petite que la portée de l'outil (122 mm avec le nez de broche), la sphère
de requête couvre tout le nuage — **aucun** index ne peut aider.

Seconde mesure, sur une pièce de 600 mm : **×48**.

D'où le critère : index si `volume_sphère < 15 % du volume de la scène`,
balayage direct sinon. Dans les deux cas le filtrage par distance reste
**exact** — l'index réduit l'ensemble candidat, jamais l'ensemble retourné,
sans quoi la garantie conservative tomberait.

### D14 — Le garde machine travaille dans le repère MACHINE

Transporter le berceau et le plateau dans le repère pièce pour chaque
orientation candidate serait coûteux. L'inverse est presque gratuit : **dans le
repère machine, l'axe de l'outil vaut invariablement `+Z`** — c'est la
définition d'une broche à axe fixe. On transporte donc le TCP, pas la machine.

Seuls les volumes portés par le berceau (`Rx(A)`) et par le plateau
(`Rx(A)·Rz(C)`) bougent, d'une rotation connue.

### D15 — Le balayage se subdivise sur une **borne prouvée**, jamais sur un
nombre d'échantillons arbitraire

Un point de l'outil se situe à au plus `reach` du TCP. Son déplacement entre
deux poses est donc majoré par

```
|Δp| ≤ |Δtcp| + reach · angle(axe₀, axe₁)
```

Majorant **strict** : c'est ce qui rend la subdivision sûre plutôt que
plausible. Toute collision plus profonde que `max_step_mm` est nécessairement
détectée.

Mesure illustrant pourquoi un échantillonnage naïf échouerait : une translation
de 10 mm demande 20 poses, une rotation de 30° en demande **129** — sur une
machine table/table, une petite rotation déplace énormément un point éloigné du
pivot.

**L'interpolation reproduit celle du contrôleur** : rampe linéaire sur (A, C)
après déroulage de C, puis cinématique directe. Interpoler les directions sur la
sphère donnerait un chemin différent de celui que la machine parcourt — et c'est
le mouvement de la machine qui fait foi.

### D16 — Le voxel plutôt que le dexel pour la matière restante

Un champ de dexels est indexé par une direction ; notre outil change
d'orientation en permanence, et un dexel Z serait faux dès qu'on bascule le
berceau. Le voxel est **isotrope**, donc indifférent à l'orientation — la
propriété exacte dont on a besoin en 5 axes.

Voxelisation par **lancer de rayons verticaux** et remplissage par parité,
plutôt que `trimesh.contains` : celui-ci exige `rtree` et un maillage
*combinatoirement* étanche, or la tessellation OCCT duplique les sommets sur les
coutures. Le lancer de rayons ne raisonne que sur la géométrie.

Précision mesurée : **exacte** sur un pavé aligné, 0,6 à 1,9 % d'écart sur des
formes courbes à 0,8 mm de pas (erreur de discrétisation, pas de fuite).

**La matière protégée n'est jamais enlevée**, même si l'outil la traverse dans
le modèle : ce serait une gouge, et masquer une gouge en la retirant du suivi
serait le pire comportement possible. Le nombre de voxels protégés touchés est
retourné par `count_gouged_voxels`.

### D17 — Exploration approchée, conclusion exacte

Répartition des rôles entre les deux tests de collision :

| | Nuage de points | B-Rep exact (`BRepExtrema`) |
|---|---|---|
| Rôle | **exploration** | **vérification** |
| Portée | centaines d'orientations/point | poses retenues seulement |
| Résolution | bornée par le pas (≈ 2 mm) | exacte |
| Coût | vectorisé, ms | ordres de grandeur au-dessus |

Même principe que DP + raffinement continu : chercher large et grossier,
conclure fin et exact. Mesure : une gouge de **0,05 mm** est détectée
(1,4137 mm³ contre π·9·0,05 = 1,4137 attendu), là où le nuage à 2 mm est aveugle.

### D18 — Toute vérification de pose porte sur la pièce **et** sur la machine

Décision imposée par une mesure, et l'anecdote mérite d'être consignée : une
première version du vérificateur ne testait que la pièce. Le raffinement
continu, libre d'optimiser le dégagement sans contrainte machine, a gagné
0,24 mm de marge en poussant l'axe Z à **60,1 mm pour une course qui s'arrête à
60,0** — un plan meilleur sur le critère optimisé et irréalisable sur la machine.

D'où `make_pose_verifier`, seul point de construction de cette fonction, partagé
par la segmentation 3+2 et le raffinement.

**Même famille d'erreur, deuxième occurrence** : le score du raffinement ne
pénalisait que l'écart angulaire entre directions voisines — un proxy
géométrique. Il a gagné 0,26 mm de marge en faisant passer la course A+C de 86 à
145°. Deux directions proches sur la sphère peuvent demander des couples (A, C)
très éloignés ; aucun critère géométrique ne le voit. Le score porte désormais
sur `|ΔA| + |ΔC|` calculé par cinématique inverse.

La leçon commune aux deux : **optimiser un proxy au lieu du critère réel produit
un plan meilleur sur le proxy et pire sur ce qui compte.** Chaque terme de coût
doit être exprimé dans l'espace où la contrainte existe — ici, l'espace des
axes machine, pas celui des directions.

### D19 — Les germes analytiques complètent la grille uniforme

Sur une face usinée en bout à la fraise à bout **droit**, l'ensemble admissible
est une lamelle de quelques degrés autour de la normale : incliner l'outil
enfonce son talon. Une grille icospherique de pas 8,6° n'a **aucune raison**
d'avoir un sommet dans cette lamelle.

Raffiner toute la sphère coûterait ×4 par niveau pour résoudre un problème
purement local. On ajoute donc la **normale exacte**, la direction lead/tilt
souhaitée, et un éventail fin autour d'elles.

Propriété garantie : les germes **ajoutent** des candidats, ils n'en retirent
aucun.

**Conséquence à ne pas manquer** : les germes ne sont pas des sommets de grille.
L'intersection d'ensembles de la segmentation 3+2, qui travaille sur des indices
de grille, devient donc une **heuristique de proposition**. D'où l'ajout d'une
**vérification exacte** de l'orientation commune proposée, en chaque point du
segment — sans quoi un segment pourrait être déclaré indexable sur une
orientation qui ne dégage pas partout.

---

## 3. Ce que M2 ne lève pas

| Limite | Pourquoi elle reste | Levée en |
|---|---|---|
| Poids d'orientation non calibrés | exige une machine réelle et des essais de coupe | après qualification |
| Gouge fine : **sondage**, pas preuve | une absence de gouge sur 12 poses ne dit rien des 5000 autres | M3 |
| Aucune gamme (`strategy_planner`, `subtractive_slicer`) | passes construites à la main | M3 |
| Performance **jamais mesurée sur Pi 5** | pas de matériel dans cet environnement | M3 |
| Import de STEP réels (mal cousus, pouces) | corpus synthétique uniquement | M3 |
| Modèle machine **non calibré** | `pivot_a`, `pivot_c`, courses, jeux = valeurs provisoires | après assemblage |

Ce dernier point est désormais **le** verrou du post-processeur, et le motif a
changé depuis M1 : les quatre portes de sécurité existent et fonctionnent. Ce
qui manque n'est plus la chaîne de sécurité, mais **ce qui la nourrit**. Générer
du G-code depuis un modèle non calibré produirait un programme géométriquement
cohérent et physiquement faux.

**±0,02 mm reste un objectif de qualification physique**, inchangé.
