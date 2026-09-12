# ADR-006 — Jalon M6 : ce que la validation coûtait, et ce qu'elle prouvait

- **Statut** : Accepté (jalon M6)
- **Date** : 2026-09-12
- **Contexte** : complète ADR-001 à ADR-005.

---

## 1. Ce que M6 apporte

M5 fermait sur trois limites nommées : le coût du calcul obligeait à ne
planifier que des **maquettes** de passes, la vérification de gouge fine
n'était qu'un **sondage**, et le corps de l'outil de tour n'était **pas
modélisé**. Les trois relevaient de la même question : *la validation sait-elle
ce qu'elle ne regarde pas ?*

Deux sont levées, une est réduite d'un facteur mesuré sans être levée — et la
distinction est faite explicitement en D50, parce que j'ai d'abord conclu
l'inverse sur une extrapolation tirée du mauvais échantillon.

| Limite M5 | Traitement M6 | État |
|---|---|---|
| Coût du calcul (maquettes de passes) | réordonnancement des deux tests exacts : **377 → 68 ms/point** | **réduite ×5,5**, pas levée |
| Gouge fine : sondage épars | **preuve** sur toute la passe par majoration du déplacement | **levée** côté porte-outil |
| Corps de l'outil de tour non modélisé | silhouette (z, r) et test de dégagement majorant | **levée** |
| Gorgeage comme opération | une passe de contour n'en est pas une | **ouverte** (nommée) |
| Performance sur Pi 5 | inchangé (pas de matériel) | **ouverte** |
| Machine non calibrée | inchangé — pas un verrou logiciel | **ouverte** |

---

## 2. Décisions

### D48 — Le garde machine rend la cause qu'il connaît, au lieu de la faire redécouvrir

Le profil du solveur d'accessibilité sur une calotte, avant tout changement :

| étage | candidats | rejets |
|---|---|---|
| E2 après cinématique | 114 | — |
| E4 test pièce exact | 114 | **2** |
| E4b garde machine | 112 | **105** |

Le solveur appelait ensuite `MachineGuard.check_pose` **une fois par rejet**,
soit 105 tests scalaires complets par point de contact, dans le seul but de
distinguer « hors course » de « collision organe ». Or `check_many` calcule
déjà ce masque — `x.contains & y.contains & z.contains` — et le jetait. S'y
ajoutait un `list(still).index(k)` dans la boucle de rejet, donc un coût
quadratique.

`check_many(..., return_travel=True)` rend désormais le masque de courses, et
le solveur en déduit la cause vectoriellement. **377 → 174 ms/point**, sans
qu'aucun résultat change : c'est la même information, calculée une fois.

La leçon est de conception, pas de micro-optimisation : *une fonction qui
calcule une information pour décider doit pouvoir la rendre*, sinon l'appelant
la recalcule — et un recalcul est aussi une occasion de divergence.

### D49 — L'ordre des deux tests exacts est un choix de coût, pas de résultat

Le test pièce coûtait 58 % du temps restant et rejetait 2 candidats sur 114 ;
la garde machine en rejetait 105. L'ordre était donc exactement l'inverse de
celui qu'il fallait.

La faisabilité étant le **ET de deux masques indépendants**, elle ne peut pas
dépendre de l'ordre. `AccessibilityConfig.guard_first=True` place donc la garde
d'abord : le test cher porte sur 7 candidats au lieu de 114. **174 → 68,4
ms/point**, soit **×5,5 au total**.

Ce n'est pas une affirmation : `test_stage_order_does_not_change_the_feasible_set`
compare les deux ordres orientation par orientation sur trois géométries du
corpus — dôme, rainure profonde, poche — et exige **zéro divergence**. C'est la
seule chose qui autorise l'inversion.

Deux effets de bord assumés, parce qu'un réordonnancement n'est jamais tout à
fait gratuit :

1. **La cause rapportée change** pour un candidat bloqué par les deux tests :
   la machine gagne. C'est le bon sens de la priorité. Allonger la jauge ne
   rend pas atteignable une orientation hors du volume machine, alors que la
   contrainte machine ne se contourne que par une réindexation ou un
   repositionnement de la pièce sur le plateau — c'est donc elle qui est
   **liante**, et c'est elle qu'il faut dire.
2. **Le champ de marges est moins complet** : le test placé en second n'est
   évalué que sur les survivants du premier. La visualisation des orientations
   rejetées en a besoin, d'où `guard_first=False` pour l'obtenir. Un seul
   modèle, un seul résultat, deux niveaux de détail de diagnostic.

### D50 — Le coût baisse de ×5,5, et la maquette reste : elle change de taille, pas de statut

C'est la décision où j'ai failli écrire l'inverse de la vérité, et le détail
mérite d'être gardé parce qu'il porte sur une **extrapolation à partir du
mauvais échantillon**.

Coût mesuré après D48–D49, sur le dôme C10 (crête 10 µm, échantillonnage
0,2 mm) :

| mode | coût par point |
|---|---|
| résolution complète | 68,4 ms (contre 377 avant M6) |
| adaptatif, stride 8 | 30,5 ms |
| adaptatif, stride 24 | 27,4 ms |

J'ai d'abord conclu qu'une passe complète devenait traitable : le groupe de
faces que mon banc mesurait comptait **3 213 points**, soit 88 s. Chiffre juste,
conclusion fausse — ce groupe n'était pas le plus gros, et une gamme de
finition en compte huit. La passe complète du dôme fait **159 899 points**, soit
environ **75 minutes** à 28 ms/point. Mesure qui l'a montré : `plan_finishing`
rapporte `3 200 / 159 899 points = 2 % de couverture` au plafond de 400.

Ce qui est donc vrai :

- le coût par point baisse de **×5,5**, donc la couverture atteignable à budget
  égal est multipliée par autant ;
- `max_points_per_pass` passe de 400 à 4 000, ce qui porte la couverture du
  dôme de 2 % à **au plus 20 %** — les huit groupes comptant tous plus de
  4 000 points, la borne `8 × 4 000 / 159 899` est atteinte au mieux ;
- **la maquette demeure.** Une gamme de finition complète sur une calotte reste
  hors de portée en mono-thread, et le rapport continue d'annoncer sa
  couverture pour que cela se lise.

Ce que M6 ne fait donc pas : lever la limite de ADR-004 / D34. Il la réduit
d'un facteur mesuré. Les leviers qui restent sont d'une autre nature —
parallélisation sur les points (le problème est séparable par construction),
propagation du cône admissible le long de la passe plutôt que résolution par
point, et réduction de la grille de directions par germe. Aucun n'est fait.

### D51 — Du sondage à la preuve : la majoration du déplacement s'applique aussi à la gouge exacte

`verify_plan_sparse` testait douze poses et ne pouvait rien dire des autres. Sa
docstring le disait, ce qui ne suffit pas : **un silence documenté reste un
silence**, et il ressemble à un verdict. Mesure de ce qu'il laisse passer : une
pose sur 120 enfoncée de 4 mm dans un bloc, soit 113 mm³ de gouge, n'est **pas
vue** par le sondage.

`certify_plan_exact` rend une preuve, par le raisonnement qui fonde déjà le
test discret conservatif (ADR-001 / D2) et la subdivision de balayage
(ADR-002) :

- une requête exacte en la pose *i* rend la garde `d_i`, distance minimale
  entre les tronçons placés et la pièce finale ;
- tout point de l'outil se déplace d'au plus
  `|Δtcp| + reach·angle(axe_i, axe_j)` entre deux poses — majorant strict,
  démontré dans `SweepChecker.displacement_bound` ;
- donc si le déplacement cumulé de *i* à *j* reste sous `d_i`, **aucune pose de
  l'intervalle ne peut toucher la pièce** : l'intervalle est certifié sans
  qu'on y calcule quoi que ce soit.

Le nombre de requêtes n'est donc pas proportionnel au nombre de poses mais au
rapport longueur de passe / garde disponible. Mesure : une passe de 120 poses
au-dessus d'un bloc, garde 20 mm, est prouvée avec **3 requêtes exactes**.

Un intervalle que ni l'une ni l'autre de ses extrémités ne couvre est
**bissecté**. La bissection termine, le majorant étant divisé par deux à chaque
étage ; elle ne termine pas si la garde tend elle-même vers zéro, c'est-à-dire
si le porte-outil frôle réellement la pièce. Ce cas n'est pas un échec de
l'algorithme mais sa réponse, et il ressort en `uncertified` **avec sa
position**. Même chose pour le budget : l'épuiser rend un certificat
*incomplet*, jamais optimiste.

### D52 — Deux physiques, deux méthodes : l'arête de coupe ne se certifie pas par la distance

Défaut de ma première version de D51, et il rendait le certificat **vide en
ayant l'air de fonctionner**. La garde était le minimum sur *tous* les
tronçons, arête comprise. Or l'arête de coupe est tangente à la surface **par
construction** : sa distance vaut zéro sur toute passe réelle. La majoration
donnait donc `d = 0` partout, aucun intervalle n'était jamais certifié, et le
verdict était « non prouvé » sur une passe parfaitement saine.

Le certificat sépare donc les deux :

- **tronçons non coupants** (goujure, col, tige, porte-outil, nez de broche) :
  ils doivent garder une distance, donc la majoration s'applique. C'est une
  **preuve** sur tout le parcours.
- **arête de coupe** : vérifiée **en chaque pose**, par test de volume. C'est
  exhaustif sur les poses, et cela reste abordable parce qu'elle ne compte
  qu'un ou deux tronçons — 120 poses en 0,4 s, là où le test à 13 tronçons en
  demandait 22 s.

`GougeCertificate.complete` exige les deux volets. Et **ce qui n'est pas
prouvé reste dit** : pour l'arête, rien entre deux poses consécutives. Le
majorant de déplacement est trop grossier pour cela — il borne le mouvement de
tout point de l'outil par `reach·angle`, alors que l'arête, elle, suit la
surface. Resserrer demande une enveloppe balayée exacte, qui n'est pas faite.

### D53 — Le corps de l'outil de tour se vérifie, mais sa géométrie ne s'invente pas

M5 vérifiait le profil de révolution contre le **bec** seul. Or ce qui interdit
de finir une gorge étroite n'est pas le bec, c'est le corps derrière lui — et
cela ne se voit sur aucun indicateur de pente.

`TurningToolBody` porte la silhouette du porte-plaquette dans le plan (z, r),
et `check_body_clearance` la teste contre le profil. Trois choix :

1. **Le moteur ne devine pas la géométrie d'un porte-plaquette.** Il vérifie
   celle qu'on lui donne. `external()` et `grooving()` fournissent des
   silhouettes paramétrées par des cotes qui veulent dire quelque chose
   (hauteur de plaquette, débord avant, débord arrière), pas une cote
   catalogue déguisée en mesure.
2. **Absence de silhouette ≠ dégagement.** `body_checked` est faux et le
   rapport l'écrit : *« corps de l'outil NON vérifié »*. Une liste
   d'interférences vide qui passerait pour un verdict serait le même défaut que
   le sondage de gouge.
3. **Le test majore.** La silhouette est échantillonnée le long de ses arêtes —
   tester les seuls sommets laisserait une arête traverser un épaulement — et
   le pas effectif est **ajouté** à la pénétration mesurée. Un test qui
   sous-estimerait l'interférence donnerait le sens d'erreur qui laisse passer
   un talonnage.

### D54 — Deux tests de la même limite physique rendent tout infaisable

Défaut trouvé en écrivant D53, et le signe qui l'a révélé mérite d'être noté :
**la pénétration rapportée ne dépendait d'aucun paramètre du corps.** Une lame
à gorger de 2 mm était refusée dans une gorge de 3 mm, avec la même valeur
qu'un corps de 20 mm.

Cause : la silhouette incluait le flanc de la plaquette, collé au bec. Son
contact contre la pente locale du profil est **déjà** mesuré par
`TurningTool.max_followable_slope_deg` et rapporté en `too_steep_zones`. Le
test le remesurait, en chaque point de passe, et concluait à l'infaisabilité
universelle.

La silhouette ne contient donc que le **corps**, à partir de la hauteur de
plaquette. Séparation des rôles :

- flanc de plaquette contre pente locale → `too_steep_zones` ;
- corps contre profil global → `body_interferences`.

Après correction, les cotes qui décident sont celles qu'on attend — et pas
celles qu'on croyait. C'est l'**arête intérieure** du corps qui touche : le
débord axial et la hauteur de plaquette changent le verdict, la hauteur du
corps ne change rien (ce qui est au-dessus de l'arête intérieure est plus loin
encore de la pièce). Les trois faits sont dans le test.

Résultat sur le corpus : arbre étagé C12 refusé avec un corps traînant 25 mm
(5,45 mm de talonnage contre la section R20), accepté quand la plaquette
soulève davantage le corps ; arbre à gorge torique C13 dégagé avec un corps
ordinaire.

---

## 3. Ce que M6 ne lève pas

| Limite | Pourquoi |
|---|---|
| **Machine non calibrée** | verrou du post-processeur, inchangé depuis M3 — il n'est pas logiciel |
| Gouge de l'arête **entre** deux poses | le majorant de déplacement est trop grossier pour une arête tangente (D52). Demande une enveloppe balayée exacte |
| **Gorgeage** comme opération | une gorge plus étroite que le corps est correctement refusée, mais `plan_turning_passes` ne génère que des passes de contour. Gorger, c'est plonger |
| **Gamme de finition complète** | 159 899 points sur le dôme, ~75 min en mono-thread. La maquette reste (D50) |
| Performance sur Pi 5 | **jamais mesurée** — aucun matériel disponible |
| Hybride fraisage + tournage dans une même gamme | les deux moteurs existent, l'ordonnancement entre eux non |
| Poids d'orientation calibrés | exige une machine |

**±0,02 mm reste un objectif de qualification physique**, inchangé depuis M1.

---

## 4. Le schéma, quatrième jalon consécutif

ADR-004 / §4 et ADR-005 / §5 relevaient le même motif. M6 en ajoute trois, et
cette fois deux d'entre eux sont dans du code que j'écrivais pour *vérifier* —
ce qui est la place la plus coûteuse :

- **la garde du certificat prise sur le mauvais ensemble de tronçons** : arête
  incluse, donc distance nulle, donc certificat vide qui tourne sans erreur
  (D52) ;
- **deux tests de la même limite physique** : le flanc de plaquette mesuré
  deux fois, donc infaisabilité universelle (D54) ;
- **une information calculée puis jetée puis recalculée** : 105 tests scalaires
  par point pour retrouver un masque déjà en main (D48).

Et le signe qui les a révélés est toujours le même : **une grandeur qui ne
varie pas quand le paramètre qui la commande varie.** La pénétration
indépendante de la taille du corps. La garde à 0,0000 mm sur une passe
manifestement dégagée. Le nombre de requêtes égal au nombre de poses alors que
la majoration devait le décorréler.

D'où la règle opératoire que ce jalon ajoute aux précédentes : **faire varier
le paramètre qui doit commander le résultat, et vérifier qu'il le commande.**
Un test qui ne fait que constater une valeur ne distingue pas un calcul juste
d'un calcul dont le paramètre n'arrive jamais. Les trois tests de D54
(`width_back`, `nose_offset`, `height`) sont écrits pour cela, y compris celui
qui exige qu'un paramètre ne change **rien**.
