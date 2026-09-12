# ADR-004 — Jalon M4 : finition et coût du calcul

- **Statut** : Accepté (jalon M4)
- **Date** : 2026-09-12
- **Contexte** : complète ADR-001 à ADR-003.

---

## 1. Ce que M4 apporte

L'ébauche de M3 ne fait que dégrossir : elle laisse le long des parois une
surépaisseur de l'ordre du rayon d'outil plus la marge de discrétisation.
**C'est la finition qui produit la surface**, et elle obéit à d'autres règles :
l'outil suit la surface au lieu de plans horizontaux, le pas transversal se
déduit d'une hauteur de crête, et l'orientation de l'axe redevient un degré de
liberté utile.

C'est donc ici que le différenciateur 5 axes sert réellement. Sur une face
plane, une orientation indexée suffit ; sur une calotte, les normales varient
trop et il faut du simultané. Le moteur tranche par la règle habituelle —
l'intersection des ensembles admissibles — et non par un réglage.

Résultat sur le dôme C10 : les trois modes apparaissent dans la même gamme
(`3+2`, `simultane`, `inaccessible`), et le rapport dit lequel s'applique à
quoi.

| Limite M3 | Traitement M4 | État |
|---|---|---|
| Finition absente | passes à crête contrôlée, 3+2 et 5 axes | **levée** |
| Coût de l'accessibilité | garde machine inversé (×75 sur l'étage), résolution adaptative | **améliorée**, pas résolue |
| Gouge fine : sondage | inchangé | **ouverte** |
| Performance sur Pi 5 | inchangé (pas de matériel) | **ouverte** |
| Tournage | inchangé | **ouverte** |

---

## 2. Décisions

### D31 — Le pas de finition se déduit d'une hauteur de crête

> **ERRATUM — rectifié en M5 (voir ADR-005 / D39).** Le titre initial de
> cette décision et le paragraphe marqué ci-dessous affirmaient que la
> formule plane est optimiste en **concave**. C'est l'inverse : elle est
> optimiste en **convexe**. Le texte est corrigé ci-dessous, l'erreur est
> conservée ici parce qu'elle a été écrite, appliquée, et qu'elle portait
> sur le seul point qui compte — le sens de l'erreur.

Entre deux passes d'un outil hémisphérique de rayon R espacées de `s` :

```
h = R − √(R² − (s/2)²)      ⇒      s = 2·√(2Rh − h²)
```

| crête visée | pas (R = 3 mm) |
|---|---|
| 2 µm | 0,219 mm |
| 5 µm | 0,346 mm |
| 10 µm | 0,489 mm |
| 50 µm | 1,091 mm |

**Valable sur un plan uniquement.** Sur une surface **convexe** la crête réelle
est plus **forte** que ce que prédit cette formule (le contact s'éloigne plus
vite de part et d'autre du point de tangence) ; sur une surface **concave** elle
est plus faible. La formule plane est donc **optimiste en convexe** — le sens
d'erreur défavorable. Mesuré à s = 0,5 mm avec un bec R3 : 15,70 µm réels sur
une bosse de 6 mm contre 10,43 µm prédits, soit ×1,5.

Le calcul exact demande la courbure locale. Il est fait depuis M5
(`geometry_core.curvature.curvature_stepover`, forme fermée exacte). Là où la
courbure n'est pas disponible, `scallop_mm` reste une **consigne indicative,
pas une garantie d'état de surface**.

### D32 — Une fraise à bout droit est refusée en finition de surface

Elle laisse une marche à chaque passe, et l'incliner enfonce son talon dans la
matière (constaté dès M1). `generate_finishing_passes` lève donc une erreur
explicite au lieu de produire une passe inexploitable.

### D33 — Deux topologies de passes, choisies sur l'étalement des normales

Les **bandes parallèles** projettent les points sur un plan tangent *moyen*.
C'est juste pour un groupe quasi plan, et faux dès que la surface se referme :
sur une calotte, le plan tangent moyen n'existe pas, les bandes se replient, et
deux points consécutifs sautent d'un bord à l'autre.

Au-delà de 60° d'étalement on passe donc en **waterline** : niveaux constants
le long de l'axe du groupe, ordonnés par angle autour de cet axe. Le chemin
fait le tour de la surface au lieu de la traverser.

**Conséquence à connaître, et elle n'est pas anodine** : sur une machine à
plateau C, faire le tour d'une calotte impose à C de tourner d'un tour complet
par niveau. Les quelques milliers de degrés de course A+C mesurés sur le dôme
ne sont donc pas un défaut de la topologie — ils sont ce qu'elle implique. Cela
entre en tension avec la contrainte de vitesse rotative, et c'est un sujet
ouvert : une topologie radiale (passes du pôle vers l'équateur) échangerait la
rotation de C contre des changements de sens plus fréquents.

### D34 — L'échantillonnage d'une passe doit être CONTIGU

Une passe de finition à 20 µm de crête compte des centaines de milliers de
points ; l'accessibilité coûte ~25 ms par point. Il faut donc en évaluer un
sous-ensemble.

Prendre un `linspace` sur toute la passe semble plus représentatif. C'est un
piège : **cela détruit la continuité du chemin.** Sur une calotte de 245 917
points, 150 points répartis sont distants de 1 640 rangs — donc très éloignés
dans l'espace. Le résultat n'est plus une passe mais une suite de sauts, et
l'orientation solver paie **13 084° de course A+C** pour un chemin qui n'existe
pas.

Un préfixe contigu est une *vraie* portion de la passe, avec sa continuité.
C'est une **maquette, pas un résumé** — et le rapport le dit : il affiche la
couverture (0,1 % à 25 % selon la face) et précise que le mode annoncé ne vaut
que pour le segment évalué.

### D35 — Le garde machine transporte le TCP, pas les organes

La première version transportait les organes machine vers le repère machine :
plusieurs milliers de points, refaits pour **chaque** couple (A, C) candidat.
Sur un point offrant 106 orientations, cela représentait **150 ms sur 199** —
les trois quarts du calcul d'accessibilité.

Or le rapport est de un à plusieurs milliers : on transporte le TCP et l'axe,
soit deux vecteurs, et les organes restent où ils sont. Le nuage devient alors
**statique** pour un organe donné, donc partageable entre toutes les
orientations candidates : un appel vectorisé par organe au lieu de cent.

Dans le repère machine l'axe outil vaut invariablement `+Z` ; dans le repère
d'un organe mobile, il devient l'image de `+Z` par la rotation inverse.

**Mesure : 199 → 51 ms par point de contact.** Le garde lui-même passe de
150 ms à 2 ms.

### D36 — Accessibilité adaptative : la faisabilité ne doit pas dépendre du classement

Le coût d'un point vient de l'*exploration* : 642 directions filtrées puis
testées. Le long d'une passe, deux points voisins ont des ensembles admissibles
qui se recouvrent largement — réexplorer toute la sphère revient à redécouvrir
la même réponse.

On résout donc complètement un point sur `stride`, et entre deux ancres on
procède par balayage avant sur un ensemble candidat réduit.

**Le défaut que cela a révélé est le plus instructif du jalon.** Les premières
versions produisaient des plans **infaisables** à certains strides (2, 4, 16) et
faisables à d'autres (8, 32) — un comportement erratique, donc inacceptable.

Diagnostic : sur une face plane usinée à l'hémisphérique, l'orientation retenue
est proche de la verticale, donc **A ≈ 5°** — tout près de la singularité, où le
gain `dC/d(axe)` vaut 10,8. Les directions voisines sur la grille correspondent
alors à des C répartis sur tout le cercle (−108°, +108°, +72°, −180°…), et la
contrainte de vitesse rotative — 10° pour un pas de 0,7 mm — **interdit de
passer de l'une à l'autre**.

La passe n'est donc réalisable *que* par une orientation commune à tous ses
points. Le calcul complet y parvenait en gardant 106 candidats ; tout élagage
qui la retire d'un seul point casse la séquence.

Deux corrections successives ont échoué avant d'identifier la cause — rendre
les classements comparables, puis propager l'ensemble du point précédent. Ni
l'une ni l'autre ne garantit la présence de l'orientation commune. La seule
correction valable a donc été de **l'injecter explicitement** dans chaque
ensemble candidat, sélectionnée par la *pire* marge sur les ancres — exactement
le critère qu'emploie la détection 3+2.

Le résultat est désormais monotone : tous les strides donnent un plan faisable,
100 % indexé, sans retournement de plateau.

| Régime | complet | adaptatif (stride 4–16) | gain |
|---|---|---|---|
| permissif (face plane dégagée) | 49 ms/pt | 20–28 ms/pt | ×1,8 – ×2,4 |
| contraint (fond de poche) | 94 ms/pt | 22–47 ms/pt | ×2,0 – ×4,3 |

Dans les deux régimes, l'adaptatif rend **le même verdict de faisabilité** que
le calcul complet.

### D37 — Une face courbe forme toujours son propre groupe

Le critère de courbure était la norme de la normale moyenne. Pour un hémisphère
elle vaut **exactement 0,5**, soit le seuil retenu : la calotte passait donc pour
une face plane d'axe vertical, et des faces planes voisines venaient s'y agréger
à 20° près.

La conséquence n'était pas anodine. Le groupe mélangeait une calotte et un plan,
or la topologie waterline suppose que chaque niveau est un **anneau** : sur un
niveau qui contient aussi une zone plane, l'ordonnancement par angle saute
radialement. Écart médian mesuré entre deux points consécutifs : **12,6 mm pour
un pas demandé de 2,2 mm**.

Le bon critère est l'**étalement** des normales dans la face, pas la norme de
leur moyenne.

### D38 — Un ordonnancement angulaire se fait autour de l'axe de la surface

Défaut de la même famille : l'angle waterline était calculé à partir des
coordonnées **absolues**, donc autour de l'origine du repère pièce. Une calotte
centrée en (30, 30, 10) donnait des angles sans rapport avec sa propre
géométrie, et le chemin sautait d'un bord à l'autre.

Après correction (coordonnées relatives au centroïde du groupe) : écart médian
**2,3 mm pour un pas de 2,15 mm** sur toutes les surfaces courbes du corpus.

---

## 3. Ce que M4 ne lève pas

| Limite | Pourquoi |
|---|---|
| **Machine non calibrée** | verrou du post-processeur, inchangé depuis M3 — il n'est pas logiciel |
| Crête réelle en concave | exige la courbure locale (D31) |
| Finition complète d'une passe longue | ~25 ms/point : une calotte à 20 µm demanderait des heures. Les plans sont des **maquettes** |
| Course rotative en waterline | faire le tour d'une calotte impose un tour de C par niveau (D33) |
| Accessibilité d'une calotte avec porte-outil trapu | 89 points sur 150 inaccessibles sur le dôme C10 : résultat correct, et il dit qu'il faut un autre outil ou une reprise |
| Gouge fine, perf. Pi 5, tournage | inchangés |

**±0,02 mm reste un objectif de qualification physique**, inchangé depuis M1.
La finition rapproche du but ; elle ne le démontre pas.

---

## 4. Ce que cinq défauts de ce jalon ont en commun

D34, D37, D38 et les deux tentatives ratées de D36 relèvent tous du même
schéma : **une quantité calculée dans le mauvais repère, ou selon le mauvais
critère, produit un résultat plausible et faux.**

- un `linspace` qui échantillonne « uniformément » mais détruit l'ordre ;
- une norme de moyenne qui sert d'indice de courbure et vaut pile le seuil ;
- un angle mesuré autour de l'origine plutôt que de l'axe ;
- deux classements indépendants supposés interchangeables.

Aucun de ces défauts ne produit d'erreur visible : ils produisent des nombres.
Ils n'ont été trouvés que parce qu'une **mesure physique** les contredisait —
écart médian entre points consécutifs, course A+C, monotonie du résultat selon
un paramètre qui ne devrait rien changer. C'est un argument pour continuer à
mesurer des grandeurs physiques plutôt que des symptômes logiciels.
