# ADR-005 — Jalon M5 : courbure locale, tournage, et une rectification

- **Statut** : Accepté (jalon M5)
- **Date** : 2026-09-12
- **Contexte** : complète ADR-001 à ADR-004, et **rectifie ADR-004 / D31**.

---

## 1. Ce que M5 apporte

Deux choses, plus une correction qui compte davantage que les deux.

**La courbure locale.** M4 calculait le pas de finition avec une formule plane.
M5 le calcule depuis la courbure normale mesurée sur le B-Rep, sous forme
fermée exacte. Le pas se resserre sur une bosse et s'élargit dans un creux.

**Le tournage.** Le module `turning_engine` cesse d'être un jeu d'interfaces :
il extrait le profil de révolution d'une pièce, mesure son défaut de circularité
et génère des passes d'ébauche, de semi-finition et de finition — ou refuse, en
nommant la zone et la cause.

**La rectification.** ADR-004 / D31 affirmait que la formule plane est optimiste
en *concave*. C'est l'inverse. Le détail est en §3, parce que c'est le point le
plus instructif de ce jalon.

| Limite M4 | Traitement M5 | État |
|---|---|---|
| Crête réelle sur surface courbe | courbure mesurée, forme fermée exacte | **levée** |
| Tournage : génération de trajectoires | profil + passes + refus motivé | **levée** |
| Gouge fine sur toute la passe | inchangé (sondage épars) | **ouverte** |
| Performance sur Pi 5 | inchangé (pas de matériel) | **ouverte** |
| Finition d'une passe complète | inchangé (maquette contiguë) | **ouverte** |
| Machine non calibrée | inchangé — ce n'est pas un verrou logiciel | **ouverte** |

---

## 2. Décisions

### D39 — Le pas de finition se calcule en forme fermée exacte, pas au premier ordre

Une première version de `curvature_stepover` employait le développement usuel

```
h = (s²/8)·(1/R + κ)      ⇒      s = √(8h / (1/R + κ))
```

Il est inutile. La géométrie exacte se résout en une ligne : deux positions
successives d'un outil sphérique de rayon R suivant un cercle osculateur de
rayon ρ = 1/|κ| ont leurs centres sur un cercle de rayon `oc = ρ + σR`
(σ = +1 bosse, −1 creux) ; la crête subsiste à l'angle médian, à la distance
`P = ρ + σh` du centre de courbure. La loi des cosinus dans le triangle
(centre de courbure, centre d'outil, crête) donne directement

```
1 − cos(θ/2) = (2Rh − h²) / (2·oc·P)

s = ρ·θ = 4ρ·arcsin( √( (2Rh − h²) / (4·oc·P) ) )
```

écrit en demi-angle pour rester bien conditionné quand ρ est grand devant
l'outil.

**Vérifié par aller-retour**, et non par plausibilité : on demande un pas, on
recalcule la crête que ce pas laisse réellement en intersectant les deux
positions d'outil, et on compare. Écart mieux que 1e-6 % pour ρ de 6 à 20 mm,
h de 2 à 150 µm, dans les deux sens.

Ce n'est pas une élégance gratuite. Le développement au premier ordre
**sous-estime** la crête sur une bosse, donc **sur-estime** le pas admissible :
c'est le mauvais sens de l'erreur, le même que celui de la formule plane, en
plus petit.

| pas s (bosse ρ = 6 mm, R = 3 mm) | biais du 1er ordre |
|---|---|
| 0,2 mm | −0,08 % |
| 0,5 mm | −0,51 % |
| 1,0 mm | −2,05 % |
| 1,5 mm | −4,68 % |

La forme fermée coûte le même `arcsin`. Il n'y avait donc aucune raison de
garder l'approximation, et une raison de ne pas la garder.

Continuité vers le cas plan : à κ = 1e-9 /mm l'expression vaut le pas plan à
1,5e-9 près en relatif, et à κ = 0 elle lui est égale au flottant près. Les
deux fonctions — `scallop_stepover` (plan) et `curvature_stepover` (courbe) —
ne peuvent donc plus se contredire, et un test l'impose.

### D40 — La formule plane est optimiste en CONVEXE

Rectification de ADR-004 / D31. Crête réellement laissée par un pas de 0,5 mm
avec un bec R3, calculée exactement :

| surface | crête réelle | prévision plane |
|---|---|---|
| plan | 10,43 µm | 10,43 µm |
| **convexe R = 20 mm** | **12,01 µm** | 10,43 µm ← optimiste |
| **convexe R = 6 mm** | **15,70 µm** | 10,43 µm ← optimiste (×1,5) |
| concave R = 20 mm | 8,86 µm | 10,43 µm ← conservatif |
| concave R = 6 mm | 5,21 µm | 10,43 µm ← conservatif |

Conséquence pratique, avec un bec R3 pour 10 µm de crête :

| surface | pas | écart au plan |
|---|---|---|
| plan | 0,4895 mm | — |
| convexe R = 22 mm (dôme C10) | 0,4591 mm | **−6,2 %** |
| convexe R = 6 mm | 0,3994 mm | **−18,4 %** |
| concave R = 20 mm (cavité C11) | 0,5311 mm | **+8,5 %** |
| concave R = 12 mm | 0,5655 mm | **+15,5 %** |

Effet mesuré sur le corpus, à crête constante de 10 µm (bec R3, même
échantillonnage des deux côtés) :

| géométrie | κ dimensionnante | pas plan → pas courbe | points |
|---|---|---|---|
| dôme C10, calotte haute | +0,04545 /mm (R22) | 0,4895 → 0,4591 mm (**−6,2 %**) | 58 066 → 65 694 |
| dôme C10, calotte basse | +0,04545 /mm (R22) | 0,4895 → 0,4591 mm (**−6,2 %**) | 46 863 → 52 995 |
| cavité sphérique C11 | −0,05000 /mm (R20) | 0,4895 → 0,5311 mm (**+8,5 %**) | 47 391 → 39 329 |
| poche à fond bombé C18 | −0,05556 /mm (R18) | 0,4895 → 0,5364 mm (**+9,6 %**) | 13 115 → 10 244 |

Le sens est le bon dans les deux cas : sur une bosse le moteur resserre et
paie en points ; dans un creux il élargit et en économise.

L'intuition qui a produit l'erreur est facile à reconstituer : « sur une bosse
les passes s'écartent, donc elles se recouvrent davantage ». C'est faux — sur
une bosse la surface **fuit** l'outil de part et d'autre du point de tangence,
ce qui creuse la crête. Le signe ne se devine pas ; il se calcule.

### D41 — La courbure dimensionnante est la plus convexe du groupe

Une face porte deux courbures principales, et un groupe de faces en porte
autant que de faces. Le pas doit majorer la crête partout, donc c'est la
courbure la **plus convexe** rencontrée qui dimensionne (`kappa_worst`).

Le signe vient de l'orientation topologique de la face, et c'est le piège :
une face `TopAbs_REVERSED` a sa normale inversée, donc sa courbure aussi.
L'ignorer échange convexe et concave, donc **inverse le sens de la
correction** — ce qui est pire que de ne pas corriger du tout. Les signes sont
vérifiés sur des géométries de rayon connu : dôme C10 (+1/22), cavité C11
(−1/20), arbre C13 (+1/18 sur les cylindres, +1/13 sur le tore).

Détail d'implémentation qui a coûté du temps : `BRepLProp_SLProps.SetSurface`
attend un `BRepAdaptor_Surface`, pas un `Geom_Surface` — sinon les dérivées
sont calculées hors du domaine borné de la face.

### D42 — Un creux plus serré que l'outil est refusé, pas raffiné

Quand ρ ≤ R dans un creux, l'outil ne touche pas le fond. Aucun pas, même nul,
n'y change quoi que ce soit : c'est l'outil qu'il faut changer.
`curvature_stepover` lève donc une `ValueError` qui le dit, plutôt que de
rendre un pas très petit qui laisserait croire à une finition correcte.

### D43 — Le tournage se ramène exactement à 2D, sans discrétisation conservative

Tout le reste du moteur travaille sur un test discret volontairement
conservatif (obstacles échantillonnés puis dilatés — ADR-001 / D2). Le tournage
n'en a pas besoin : une pièce de révolution est entièrement décrite par sa
silhouette `(z, r)`, et une passe de tournage est une courbe dans ce plan. La
géométrie y est **exacte**, et le plan de passes est un problème 2D.

C'est la justification du module séparé plutôt que d'un mode du fraiseur :
ce n'est pas la même physique, ni la même représentation, ni la même
vérification.

`revolution_profile` échantillonne la surface, projette sur l'axe, et prend
`r.max()` par tranche de z. Le maximum, pas la moyenne : ce qu'il faut enlever
est borné par la matière la plus éloignée de l'axe.

### D44 — L'ovalité se mesure sur θ, et robustement

Deux défauts successifs, tous deux produisant un nombre plausible et faux.

**Premier défaut : le mauvais axe de mesure.** L'indicateur de circularité
était `r.max() − r.min()` sur la tranche. Sur un arbre étagé, une tranche qui
chevauche un épaulement contient les deux diamètres : l'arbre C12, parfaitement
tournable, était déclaré non revolutif à **19,9 mm** près — c'est-à-dire
l'écart entre deux de ses diamètres, pas un défaut de circularité. La variation
**axiale** avait été confondue avec la variation **angulaire**. L'ovalité se
mesure donc sur θ : rayon maximal par secteur angulaire, puis étendue sur les
secteurs.

**Second défaut : la mesure non robuste.** Corrigé sur θ, l'indicateur donne
encore, sur l'arbre C12, **2,77 mm au maximum pour une médiane de 0,003 mm** —
une tranche unique, dont un secteur chevauche un épaulement, suffit. Un
min–max est un estimateur à point de rupture nul. L'indicateur est donc `P95 − P5` sur les secteurs, avec un nombre
minimal de secteurs peuplés (`max(8, n_theta // 3)`) sans lequel la tranche est
écartée, et le rapport annonce le **P95** sur les tranches plutôt que le
maximum.

Résultat sur le corpus (P95 sur les tranches) : arbre étagé C12 à
**0,053 mm**, arbre à gorge torique C13 à **0,005 mm**, contre **5,800 mm**
pour C14 qui porte deux méplats fraisés. Le seuil de décision est à 0,1 mm, et
les trois valeurs en sont loin — dans le bon sens chacune.

### D45 — L'ébauche descend jusqu'au rayon MINIMAL du profil

La boucle d'ébauche s'arrêtait au rayon **maximal** du profil. Sur un arbre
allant de R20 à R4 elle produisait donc deux passes et laissait tous les étages
intacts — sans rien signaler. Elle descend maintenant jusqu'à `target.min()`.

Sur C12 (brut R22, profondeur de passe 1,5 mm, surépaisseur 0,2 mm) :
**12 passes d'ébauche puis une finition**, au lieu de 2 passes. La dernière
ébauche n'est pas à rayon constant : c'est un contour suivant le profil à la
surépaisseur, de façon que la finition trouve une épaisseur de copeau
uniforme. Section enlevée annoncée : 660,1 mm² dans le plan (z, r).

### D46 — Un profil plus raide que le dégagement de l'outil est refusé avant génération

Un outil de tournage ne suit pas une pente supérieure à `90° − angle de
dégagement`. Ce n'est pas un problème de trajectoire : aucun recalcul de passes
n'y remédie. La vérification se fait donc **avant** de générer quoi que ce
soit, et le rapport nomme les zones fautives (sur C12 avec un outil à 45° de
dégagement : les épaulements en z ∈ [14,88 ; 16,04] et z ∈ [35,29 ; 36,46]).
Un brut de rayon inférieur au profil est refusé de la même manière, et le
rapport le dit en un mot — `brut`.

### D47 — Le basculement du mode C reste une transition verrouillée

Rappel, pas nouveauté : ADR-001 / D8. Passer d'indexation à broche continue
invalide l'approbation de sécurité et exige une nouvelle simulation.
`require_c_mode` le fait respecter, et un test vérifie que la transition lève.
Rien dans M5 n'affaiblit cette règle : le tournage produit des **passes**, il
ne produit aucune commande machine.

---

## 3. Une erreur de documentation est une erreur d'ingénierie

Le défaut le plus sérieux de ce jalon n'est pas dans le code : il est dans la
documentation de M4, qui affirmait le contraire de la vérité sur le seul point
qui compte — **le sens de l'erreur**.

Une formule imprécise se rattrape par une marge. Une formule dont on croit
connaître le sens du biais, et qui biaise dans l'autre sens, ne se rattrape
pas : la marge qu'on ajoute va du mauvais côté. D31 recommandait implicitement
de se méfier des congés intérieurs ; c'est exactement là que la formule plane
était **conservative**, tandis que les bosses, non signalées, sortaient de
tolérance sans indicateur.

L'erreur est conservée en place dans ADR-004, marquée comme erratum, plutôt que
réécrite silencieusement. Un registre de décisions qui se corrige sans trace
perd ce qui le rend utile.

Deux conséquences pour la suite :

1. **Toute affirmation de sens (« optimiste », « conservatif », « majore »)
   doit être adossée à un test**, pas à un raisonnement. Le test
   `test_plane_formula_is_optimistic_on_CONVEX_surfaces` existe pour cela, et
   son nom porte la rectification.
2. Une garantie conservative n'a de valeur que si elle est **mesurée dans le
   sens où elle est invoquée**. ADR-001 / D2 tient parce que la dilatation par
   δ est prouvée majorante ; D31 ne tenait pas parce que personne n'avait
   calculé la crête exacte.

---

## 4. Ce que M5 ne lève pas

| Limite | Pourquoi |
|---|---|
| **Machine non calibrée** | verrou du post-processeur, inchangé depuis M3 — il n'est pas logiciel |
| Gouge fine sur toute la passe | `verify_plan_sparse` reste un sondage, pas une preuve |
| Finition d'une passe complète | ~25 ms/point : les plans restent des **maquettes** contiguës |
| Performance sur Pi 5 | **jamais mesurée** — aucun matériel disponible |
| Tournage : collision porte-outil | le profil 2D est exact, le dégagement du porte-plaquette n'est pas encore modélisé |
| Hybride fraisage + tournage dans la même gamme | les deux moteurs existent, l'ordonnancement entre eux non |
| Poids d'orientation calibrés | exige une machine |

**±0,02 mm reste un objectif de qualification physique**, inchangé depuis M1.
M5 rend le pas de finition juste ; il ne dit rien de l'état de surface obtenu.

---

## 5. Le même schéma, pour la troisième fois

ADR-004 / §4 relevait que cinq défauts de M4 partageaient un schéma : *une
quantité calculée dans le mauvais repère, ou selon le mauvais critère, produit
un résultat plausible et faux.* M5 en ajoute quatre :

- une ovalité mesurée sur l'étendue **axiale** d'une tranche au lieu de sa
  variation **angulaire** (D44) ;
- un min–max là où il fallait un quantile (D44) ;
- une boucle bornée par le rayon **maximal** au lieu du minimal (D45) ;
- un signe de courbure pris sans tenir compte de l'orientation topologique
  (D41).

Aucun ne lève d'exception. Tous produisent des nombres. Ils ont été trouvés
parce qu'une grandeur **physique** les contredisait : 19,9 mm d'ovalité sur un
arbre cylindrique, 2 passes pour enlever 16 mm de rayon, une crête exacte
calculée séparément de la formule censée la prédire.

La leçon opératoire est stable sur trois jalons : **ne jamais vérifier une
quantité géométrique contre son propre calcul**. On la vérifie contre une
mesure obtenue autrement — un aller-retour, une intersection exacte, une course
d'axe, une monotonie que la physique impose.
