# ADR-007 — Jalon M7 : rattacher les nombres au réel

- **Statut** : Accepté (jalon M7)
- **Date** : 2026-09-12
- **Contexte** : complète ADR-001 à ADR-006.

---

## 1. Ce que M7 apporte

Un manque de fond des six premiers jalons, que je n'avais jamais assez mis en
avant : **toutes les marges rapportées jusqu'ici étaient calculées sur une
machine parfaite.** Les jeux valaient 0,0, les pivots A et C étaient à leur cote
nominale, les axes linéaires exactement orthogonaux. Une marge de 0,7 mm
annoncée sur une poche était une marge *géométrique*, pas une marge machine.

M7 mesure la machine, compense ce qui est mesuré, et borne ce qui ne l'est pas.
C'est aussi le jalon qui lève la **moitié logicielle** du verrou du
post-processeur — pas la moitié physique.

| Limite M6 | Traitement M7 | État |
|---|---|---|
| Marges sur une machine parfaite | erreurs mesurées, compensées, budget d'incertitude | **levée** |
| Post-processeur : aucun G-code | émission dans un fichier, derrière les portes, aller-retour vérifié | **levée** (moitié logicielle) |
| `assembly_calibration` ébauche | procédures des étapes mesurables, vérifiées par erreur injectée | **levée** |
| `probing_service` ébauche | palpeur simulé, ajustements, incertitudes par jackknife | **levée** |
| **Machine non construite ni qualifiée** | inchangé | **ouverte** |
| Envoi réel à LinuxCNC | `linuxcnc_gateway` reste verrouillé | **ouverte, volontairement** |

---

## 2. Décisions

### D55 — Une machine non mesurée n'a pas une erreur nulle, elle a une incertitude inconnue

C'est la distinction qui fonde tout le module. `MachineGeometry.nominal()` porte
`measured=False`, et `position_uncertainty_mm` **lève** dans cet état plutôt que
de rendre zéro. Lire des zéros reviendrait à croire une machine parfaite, ce qui
est exactement l'erreur que six jalons de marges géométriques ont rendue facile.

### D56 — Une erreur mesurée est compensable ; l'incertitude de sa mesure ne l'est pas

Deux corrections de nature différente sur une cinématique XYZAC :

**La position se corrige exactement.** Les axes linéaires translatent la broche
dans le repère machine, donc tout écart de position de la pièce se rattrape en
déplaçant la commande — sans approximation, y compris l'équerrage et l'échelle,
qui passent dans l'inverse du trièdre mesuré.

**L'orientation se corrige par re-résolution.** Les axes réels n'étant pas
exactement +X et +Z, la formule fermée ne donne plus la bonne direction. On
repart de la solution nominale et on raffine par Gauss-Newton amorti sur les
axes mesurés.

Mesuré par injection d'erreur connue, pose à 65 mm des pivots :

| erreur injectée | écart sans compensation | après compensation |
|---|---|---|
| pivot A décalé de 0,37 mm | 245 µm | **0,0000 µm** |
| axe A incliné de 0,20° | 98 µm / 0,128° | 0,0000 µm / 0,000000° |
| axe C incliné de 0,15° | 229 µm / 0,260° | 0,0000 µm / 0,000000° |
| équerrage 0,05° + échelle 120 ppm | 31 µm | 0,0000 µm |
| tout cumulé | 261 µm / 0,327° | 0,0000 µm / 0,000000° |

Ce qui reste est donc l'**incertitude des mesures**, et c'est le seul plancher
réel. Elle grandit avec le bras de levier : une incertitude d'orientation d'axe
de 0,01° vaut 17 µm à 100 mm du pivot.

`position_uncertainty_mm(worst_case=True)` **somme** les contributions, choix
conservatif qu'exige un budget de sécurité — même discipline que l'inflation du
champ d'obstacles (ADR-001 / D2). La composition en quadrature existe, donne un
chiffre plus flatteur, et ne doit pas servir à décider d'une garde.

### D57 — L'amorce choisit *laquelle* des solutions, pas *s'il y en a une*

Rectification d'une affirmation que j'avais écrite trop vite. J'avais énoncé que
l'amorce décide de la convergence. Mesure : les deux amorces convergent, au même
résidu (2e-9 °). Elle décide de la **solution atteinte** — dans la géométrie où
l'axe C est nominal, une amorce (0, 0) aboutit à C = −89,80° et une amorce
nominale à C = +90,20°, pour la même direction d'outil : **180° de plateau
d'écart**.

C'est la raison de fond pour laquelle `compensate_pose` exige les valeurs
nominales en entrée : choisir la branche est une décision de trajectoire —
continuité, singularité, courses — et la laisser à un solveur numérique la
rendrait invisible.

Accessoirement l'amorce décide du coût : 3 à 8 itérations depuis la solution
nominale, 20 à 24 depuis (0, 0). La borne d'itérations vaut 60 et non 20, parce
que le cas difficile en demande 22 et qu'une borne à 20 le faisait échouer d'un
cheveu en rendant 0,044° de résidu.

### D58 — Près de la singularité, la compensation coûte de la course rotative

Fait physique isolé à ce jalon, avec une conséquence de planification. Corriger
une erreur d'orientation minuscule demande une grande rotation de plateau quand
A tend vers 0 : un défaut d'axe de 0,15° coûte **16,6° de C à A = 0,5°**, contre
1,5° à A = 5°.

La compensation n'est donc **pas neutre vis-à-vis des courses rotatives**, et un
plan qui frôle A = 0 peut devenir infaisable après compensation alors qu'il
passait avant. C'est une raison de plus de traiter la singularité comme un
problème de mouvement (ADR-003) et non de position.

### D59 — La localisation des axes se mesure, et sa composante axiale n'existe pas

La procédure qui lève le verrou nommé par le post-processeur : une sphère de
référence solidaire du plateau est palpée à plusieurs valeurs de l'axe. Ses
centres décrivent un cercle dont la **normale** est la direction de l'axe et
dont le **centre** est un point de l'axe.

Deux propriétés à énoncer parce qu'elles ne sont pas évidentes :

1. **La position le long de l'axe n'est pas observable, et n'a aucun effet
   cinématique** — tourner autour de deux points d'une même droite donne la même
   transformation. La procédure ne rend donc que la composante
   **perpendiculaire**, et c'est vérifié : sur un offset injecté de
   `[0,10 ; −0,20 ; 0,30]` pour l'axe A (nominalement selon X), la composante X
   revient à 0,0007 mm — soit zéro, correctement.
2. **Le rayon auquel on place la sphère est le seul levier gratuit.**
   L'incertitude d'orientation vaut résidu / rayon du cercle décrit : passer de
   30 à 70 mm la divise par deux (0,0122° → 0,0052° à 10 µm de bruit).

Le signe de la normale est fixé par le **sens de rotation mesuré**, jamais par
la proximité au nominal : se recaler sur le nominal ferait retrouver le nominal,
ce qui est exactement l'erreur que la procédure doit éviter.

Erreur injectée retrouvée, sur l'ensemble de la séquence :

| bruit de palpage | erreur dir. A | erreur dir. C | erreur offset A | budget à 100 mm |
|---|---|---|---|---|
| 1 µm | 0,0028° | 0,0011° | 6,2 µm | 30 µm |
| 3 µm | 0,0084° | 0,0034° | 18,7 µm | 74 µm |
| 10 µm | 0,0280° | 0,0114° | 62,4 µm | 229 µm |

Le budget géométrique d'un kit calibré avec un palpeur à 3 µm est donc de
**74 µm à 100 mm des pivots**, pire cas. Cela contredit directement tout
±0,02 mm, et c'est l'un des résultats les plus utiles de ce jalon.

### D60 — Un ajustement mal posé rend un nombre qui ressemble à une mesure

Le défaut le plus instructif de M7, et il était dans mon propre banc de
vérification. Mon palpeur simulé prenait ses huit points **sur une seule
latitude** de la sphère. Or des points d'un même cercle appartiennent à une
infinité de sphères : le problème n'a pas de solution unique. `numpy.lstsq`
rendait pourtant un centre, ce centre avait l'air d'une mesure, et la
localisation d'axe qui en découlait se trompait de **178°** avec un résidu de
1,1 mm.

Le signe qui l'a révélé : **le résidu ne variait pas avec le bruit de
palpage.** Un défaut statistique aurait suivi le bruit ; celui-là était
systématique.

Deux corrections, et la première compte plus :

1. `fit_sphere` **refuse** désormais une configuration dégénérée, en testant le
   conditionnement du système (rapport des valeurs singulières), avec un message
   qui dit quoi faire — palper sur au moins deux latitudes. Le garde est dans la
   fonction d'ajustement, parce que n'importe quel appelant peut lui donner un
   mauvais jeu de points. `fit_plane_normal` a le même garde pour des points
   colinéaires.
2. Le palpeur simulé échantillonne deux latitudes plus le pôle, comme une vraie
   routine.

### D61 — Les incertitudes sortent d'un jackknife, pas d'une formule fermée

Défaut grave et de mauvais sens. Les incertitudes venaient de `résidu / rayon`
et `résidu / √n`. Mesure contre erreur injectée : elles **sous-estimaient**
l'erreur réelle d'un facteur ~3,7, constant sur trois niveaux de bruit.

Une incertitude sous-estimée est exactement la confiance fabriquée que ce module
existe pour empêcher.

Cause : ces formules supposent un **cercle complet**, alors qu'on mesure un arc
— 160° pour C, et seulement 80° pour A, borné par la course du berceau. Un arc
partiel contraint beaucoup moins bien la normale, et aucune des deux formules ne
le voit.

Remplacées par un **jackknife** : n réajustements à un point retiré, dont la
dispersion donne l'erreur type. Il voit l'étendue angulaire, le nombre de points
et le bruit d'un seul coup, sans qu'on ait à les modéliser. Le coût est
négligeable (n moindres carrés de taille 3). Après correction, l'incertitude
annoncée **majore** l'erreur réelle d'un facteur ~1,28, et c'est vérifié par un
test sur trois niveaux de bruit et les deux axes.

Le fait que la localisation de A soit structurellement moins bonne que celle de
C sur cette machine — le berceau ne fait pas le tour — sort donc tout seul du
jackknife, au lieu d'être une note de bas de page.

### D62 — Cinq étapes exigent la machine, et ne sont jamais rapportées réussies

`HARDWARE_ONLY` porte la distinction dans une donnée, pas dans un commentaire :
test de câblage, sens des axes, courses réelles, caméra, et **pièce d'épreuve
usinée puis mesurée**. Chacune rend `passed=False` avec son remède.

Ce que le jumeau valide : la **mathématique** d'une procédure — l'ajustement, la
propagation d'incertitude, la sensibilité au bruit et au nombre de points. Ce
qu'il ne valide pas : tout ce qu'il ne modélise pas — déformations thermiques,
flexion sous effort de palpage, hystérésis du déclencheur, défauts de forme de
la sphère de référence.

Le rapport de calibration est donc **incomplet, et c'est le résultat correct**.
`CalibrationRecord` distingue trois états qu'il ne faut pas confondre :
`geometry.measured` (la cinématique n'est plus provisoire),
`geometry_complete` (toutes les étapes non matérielles sont faites), et
`qualified` (pièce d'épreuve mesurée).

`tolerance_statement()` est le **seul endroit du projet autorisé à énoncer une
précision**, et il refuse d'en énoncer une tant que `qualified` est faux. Un test
vérifie qu'aucun « 0,02 » n'en sort.

### D62b — L'équerrage se mesure entre deux faces, jamais sur une seule

Défaut de même famille que D60, et il est allé plus loin : ma procédure
`measure_squareness` mesurait **la mauvaise grandeur**.

Elle palpait un plan unique et comparait sa normale à la normale nominale. Deux
problèmes, dont le second est rédhibitoire :

1. cette normale porte l'orientation du **montage** de l'étalon autant que
   l'équerrage machine, et les deux sont indiscernables sur une seule face ;
2. elle ne voit même pas l'équerrage. Un plan à z constant subit une distorsion
   **uniforme** du trièdre — tous ses points se décalent pareil — donc sa
   normale lue est inchangée. Mesure : un équerrage XZ injecté de 0,30° donnait
   une valeur **bit pour bit identique** à celle d'une machine droite.

La bonne mesure est l'angle **entre deux faces** d'un cube étalon. Il est
invariant par rotation de l'étalon — si le cube est posé de travers, les deux
normales tournent ensemble — donc il ne reste que le défaut machine. Les trois
paires donnent les trois angles **séparément**, ce qui lève au passage une
limite que j'avais documentée comme irréductible dans la version précédente.

Corollaire de modélisation, trouvé en même temps : le palpeur simulé ne
convertissait pas les positions en **coordonnées d'axes**. Un palpeur réel rend
les valeurs des axes au déclenchement, donc un défaut d'équerrage ou d'échelle
distord la lecture — et c'est par cette distorsion, et pas autrement, qu'on peut
l'apercevoir. Sans cette conversion, le jumeau ne portait aucun défaut du
trièdre linéaire.

### D63 — Poster exige une géométrie mesurée ; envoyer exige une machine qualifiée

Séparation des ateliers, portée par deux gardes distincts :

- **poster un programme** exige les quatre portes franchies et une géométrie
  **mesurée**. Pas une machine qualifiée — on poste avant de qualifier.
- **envoyer à la machine** exige tout, pièce d'épreuve comprise. C'est
  `linuxcnc_gateway`, et il reste verrouillé.

L'ordre des refus n'est pas indifférent et un test le fixe : la porte de
sécurité passe **avant** de regarder la calibration, qui passe avant tout calcul.
Si l'état n'autorise pas la génération, rien d'autre n'a de sens ; si la
géométrie n'est pas mesurée, tout calcul ultérieur serait faux avec élégance.

L'en-tête du fichier porte l'énoncé de tolérance mot pour mot, le hash de
calibration, le budget géométrique, et le fait que les avances ne sont **pas
qualifiées** (`recipe_profiles` est toujours une ébauche). Un opérateur qui
ouvre le fichier tombe dessus avant la première ligne de mouvement.

**L'aller-retour est ce qui rend l'émetteur vérifié** : un émetteur contrôlé
contre son propre calcul ne vérifie rien. On relit donc le G-code produit et on
rejoue la cinématique réelle sur les valeurs **relues**.

| vérification | écart position | écart direction |
|---|---|---|
| aller-retour sur la géométrie **mesurée** | 0,078 µm | 0,000048° |
| aller-retour sur la géométrie **vraie** | 14,4 µm | 0,0072° |
| budget annoncé à 100 mm | **54,3 µm** | — |

Les trois lignes disent trois choses différentes. La première est la fidélité
numérique de la chaîne émission → relecture → cinématique : 0,078 µm, soit la
**quantification du format** à quatre décimales, plancher que rien en aval ne
peut franchir. La deuxième est l'erreur résiduelle de calibration. La troisième
doit **majorer** la deuxième, sinon elle n'annonce rien — et c'est un test.

### D64 — Le dossier de calibration entre dans le hash du setup

Une recalibration change les pivots A et C, donc la géométrie contre laquelle
les collisions ont été vérifiées. Elle doit invalider une approbation exactement
comme un bridage déplacé. `Setup.calibration_hash` entre donc dans l'empreinte.

Et le trou que ce garde ferme : le post-processeur **refuse** si le dossier
fourni n'est pas celui sous lequel le montage a été approuvé. Approuver sous une
calibration et poster sous une autre annule la signification de l'approbation.

### D65 — Aucun rapide vers un point de contact, et le manque est écrit

Défaut de l'émetteur, trouvé en relisant mon propre diff : le premier point de
chaque opération sortait en `G0`, c'est-à-dire **un rapide dans la pièce**.

Les mouvements d'approche et de dégagement ne sont pas générés par ce module,
qui ne connaît pas le plan de dégagement des opérations. Le défaut prudent est
donc l'avance travail partout, `is_rapid` est respecté quand la trajectoire le
fournit, et le manque figure dans l'en-tête du fichier — pas comblé par une
invention.

---

## 3. Ce que M7 ne lève pas

| Limite | Pourquoi |
|---|---|
| **Machine non construite ni qualifiée** | la moitié physique du verrou. Cinq étapes de calibration l'exigent, dont la pièce d'épreuve |
| Envoi réel à LinuxCNC | `linuxcnc_gateway` verrouillé, délibérément |
| Erreurs non géométriques | thermique, flexion sous effort, hystérésis, défauts de forme de l'étalon : non modélisées, donc hors budget |
| Erreurs d'échelle des vis | modélisées et compensables, mais aucune procédure ne les mesure (il faut un interféromètre ou une règle étalon) |
| Avances et vitesses | `recipe_profiles` toujours une ébauche. Émises prudentes et déclarées non qualifiées |
| Approche et dégagement | non générés (D65) |
| Gouge de l'arête entre deux poses | inchangé depuis M6 |
| Gorgeage, hybride fraisage/tournage | inchangés depuis M6 |
| Performance sur Pi 5 | **jamais mesurée** |

**±0,02 mm reste un objectif de qualification physique.** M7 rend le chiffre
*calculable* — 74 µm de budget géométrique à 100 mm pour un palpeur à 3 µm — et
ce calcul dit que l'objectif n'est pas acquis, ce qui est précisément son
utilité.

---

## 4. Le schéma, cinquième jalon consécutif — et cette fois dans le vérificateur

ADR-004 / §4, ADR-005 / §5 et ADR-006 / §4 relevaient le même motif. M7 en
ajoute cinq, **tous dans du code écrit pour vérifier ou pour mesurer** :

- un ajustement mal posé qui rend un nombre ressemblant à une mesure (D60) ;
- une procédure qui mesurait la mauvaise grandeur : l'orientation d'une face au
  lieu de l'angle entre deux, sur une géométrie où la première est de surcroît
  aveugle au défaut cherché (D62b) ;
- un signe de normale déduit des extrémités d'un arc de 300°, où le produit
  vectoriel ne reflète plus le sens de rotation ;
- une variable `ang` du jackknife qui **écrase** le paramètre `ang` portant les
  angles commandés : le tri des positions devenait arbitraire et l'erreur
  rapportée valait 179,999° au lieu de 0,001° ;
- une incertitude sous-estimée d'un facteur 3,7 (D61).

Plus **deux affirmations de docstring fausses**, écrites par plausibilité et
corrigées par la mesure : que l'amortissement évite une divergence (il évite un
système normal exactement singulier, qui *lève*), et que l'amorce décide de la
convergence (elle décide de la branche).

Le signe révélateur est toujours le même, et il s'affine : **une grandeur qui ne
varie pas quand le paramètre qui la commande varie.** Le résidu insensible au
bruit de palpage. Le rapport incertitude/erreur constant sur trois niveaux de
bruit. La valeur d'équerrage identique **bit pour bit** avec et sans défaut
injecté. La pénétration indépendante de la taille du corps, au jalon précédent.

La règle de M6 — faire varier le paramètre qui doit commander le résultat — se
complète donc de son revers, que ce jalon impose : **quand une grandeur reste
stable alors qu'un paramètre varie, c'est une information, pas une
confirmation.** Un résidu qui ne bouge pas n'est pas un bon résidu ; c'est un
résidu qui ne mesure pas ce qu'on croit.
