# ADR-023 — Le choix de l'outil contre la marge de tranchage

## Contexte

Deux critères répondaient à « cet outil entre-t-il », et **celui qui décidait
n'était pas celui qui tranchait**.

- `outil_d_ebauche` (étape 2) retient le plus gros qui entre et atteint le
  fond : une boule de rayon *r* circulant dans l'espace libre ;
- le découpage (étape 4) exige en plus une **marge** entre l'outil et la
  pièce — `marge_de_tranchage`, **1,87 mm** au pas de 1 mm — sans quoi il
  proposerait des positions que le contrôle de gouge refuserait ensuite.

Sur une poche de 12 mm, une Ø 10 entre sans peine (10 < 12) et le découpage ne
lui laisse **aucune** position (5 + 1,87 = 6,87 > 6). Le logiciel annonçait un
outil, puis rendait un parcours vide.

Le message était exact — il nommait la marge et donnait les deux leviers — mais
le logiciel **aurait pu prendre la Ø 6 lui-même**. C'est la seizième occurrence
de la même famille : une grandeur lue comme si elle mesurait ce qu'on voulait.

## La fausse bonne idée, essayée et mesurée

Le réflexe était d'exiger la marge **dès l'étape 2** : retenir le plus gros
outil tel que `r + marge ≤ rayon_au_fond_mm`. Mesuré sur le corpus avant d'être
écrit :

| creux | fond | choisi | « tranchables » selon ce critère |
|---|---|---|---|
| poche 12 × 24 × 9 | Ø 11,2 | Ø 10 | Ø 6, Ø 3 ✔ |
| poche **20 × 9 × 10** | Ø 9,0 | Ø 6 | **Ø 3 seulement** ✘ |

Le critère écarte bien la Ø 10 des poches de 12 mm — et il écarte **aussi la
Ø 6 des poches de 9 mm de profondeur, qui la reçoivent très bien**.

La raison est nette : `rayon_au_fond_mm` est une **boule inscrite en 3D**, donc
bornée par la profondeur ; la marge du découpage est **latérale**, mesurée dans
le plan de tranchage. Une poche peu profonde a une petite boule inscrite et
beaucoup de place latérale.

**Un critère qui refuse des outils qui marchent n'est pas prudent, il est
faux.** Et il aurait coûté une Ø 3 là où une Ø 6 travaille.

## Décision

Poser la question à celui qui sait y répondre : **le découpage lui-même**, une
fois la direction connue.

`parcours_du_creux` essaie l'outil retenu ; si le parcours est vide, il descend
d'un cran parmi les outils qui entrent, du plus gros au plus petit, et s'arrête
au **premier qui donne un parcours** — le plus gros qui marche, celui qu'un
usineur prendrait. Descendre jusqu'à la Ø 3 serait une heure de travail pour ce
qu'une Ø 6 fait en quelques minutes.

### Pourquoi à l'étape 4, et pas à l'étape 2

Parce que la marge est latérale, donc dépendante de l'**orientation**, qui n'est
décidée qu'à l'étape 3. Le coût est un tranchage par outil écarté, et seulement
pour les creux dont le premier choix échoue.

### Pourquoi l'orientation n'a pas à être revérifiée

Un outil plus fin de la même famille est **contenu** dans le plus gros : même
porte-outil, même jauge, arête et tige de rayon plus petit. Toute pose dégagée
pour le gros l'est donc pour le fin.

C'est une hypothèse, donc elle est **vérifiée tronçon par tronçon** par un test
plutôt que supposée — exactement comme les deux hypothèses de l'ADR-019.

### Le verdict est reconstruit, pas rapiécé

L'écran annonce l'outil du **verdict**. Si celui-ci n'était pas refait, il
dirait Ø 10 au-dessus d'un parcours de Ø 6 — un outil remplacé en silence ferait
mentir toutes les phrases d'avant. Le verdict porte donc `repli_de_mm`, et sa
phrase dit : *« La Ø 10 mm y entre, mais le découpage ne lui laisse aucune
position. »*

Descendre d'outil n'est pas une promesse de réussir : quand aucun ne marche, le
refus d'origine est conservé tel quel, avec ses deux leviers.

## Ce que cela produit

Les 20 creux usinables du corpus, tracés avant et après :

| | |
|---|---|
| parcours vides | **6 → 0** |
| replis d'outil | 6 |

**Tous les creux usinables du corpus ont désormais un parcours.** Les six
replis :

| creux | cotes | outil | poses obtenues |
|---|---|---|---|
| C09 trous 4 faces #1 | 15 × 10 × 10 | Ø 6 → **Ø 3** | 391 |
| C09 trous 4 faces #2 | 10 × 15 × 10 | Ø 6 → **Ø 3** | 391 |
| C09 trous 4 faces #3 | 10 × 15 × 10 | Ø 6 → **Ø 3** | 409 |
| C09 trous 4 faces #4 | 15 × 10 × 10 | Ø 6 → **Ø 3** | 349 |
| C21 creux multiples #3 | 12 × 24 × 9 | Ø 10 → **Ø 6** | 90 |
| C21 creux multiples #4 | 12 × 24 × 9 | Ø 10 → **Ø 6** | 90 |

Les quatre trous de C09 traînaient depuis l'ADR-016 : ils comptaient parmi les
« 4 parcours vides » de toutes les mesures précédentes, et ils étaient refusés
pour exactement cette raison — une Ø 6 dans un trou de 10 mm, 3 + 1,87 = 4,87
contre une demi-largeur de 5, à 0,13 mm près. Ils n'avaient jamais été des
refus de la pièce, seulement du choix d'outil.

Aucun creux qui marchait n'a changé d'outil : descendre « par prudence » aurait
été une dégradation déguisée en sécurité, et un test l'interdit.

Sur C21, l'écran passe de **quatre creux avec un rang** à **six**, et la
recherche des creux coûte 14 s au lieu de 10 — le prix des tranchages
supplémentaires, payé seulement par les creux dont le premier choix échoue.

## Ce que cela ne fait toujours pas

- la marge reste celle du **pas de grille** : affiner le pas la réduit, et
  c'est le vrai levier pour les creux étroits. Rien ne le propose encore ;
- le repli ne change pas l'**ordre** des étapes : l'étape 2 annonce toujours un
  outil qu'elle pourrait savoir inutilisable dans certains cas ;
- la **reprise** reste calculée sur le choix d'origine.
