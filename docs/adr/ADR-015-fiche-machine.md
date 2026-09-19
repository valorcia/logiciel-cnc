# ADR-015 — La fiche de la machine, et la provenance de chaque cote

## Contexte

La machine n'existe pas encore. Tout ce que le logiciel sait d'elle vient du
dessin, et le dessin n'est pas la machine : les bras ne feront pas 250,0 mm, le
pivot du berceau ne sera pas à Z = −40,000, et le plateau ne sera pas
parfaitement centré.

Jusqu'ici ces cotes étaient dispersées : neuf champs dans `Reglages` (en
mémoire seulement, perdus à chaque fermeture), des constantes dans
`default_xyzac_kit()`, d'autres dans `DeltaLineaire`. Aucune ne disait d'où
elle venait, et **rien ne survivait au redémarrage** — c'est-à-dire que des
cotes relevées sur la machine auraient été à retaper chaque matin, donc jamais
relevées.

## Décision

`machine_model.fiche` porte **46 cotes**, chacune avec quatre choses, et la
quatrième est celle qui manque à tous les écrans de réglages :

1. sa **valeur** et son unité ;
2. ce qu'elle **change** — faisabilité, temps, précision ou sécurité ;
3. comment la **mesurer**, en une phrase, une fois la machine devant soi ;
4. sa **provenance** : plan, essai, mesure ou calibration.

### La provenance ne se choisit pas

C'est la seule règle du module, et elle est stricte : **taper une valeur ne la
rend pas mesurée**.

- `regler(v)` → `ESSAI`, quel que soit le soin mis à la saisie ;
- `mesurer(v, moyen=…)` → `MESURE`, et `moyen` est **obligatoire et non vide** ;
- `calibrer(v, procedure=…)` → `CALIBRE`, écrit par la procédure elle-même.

Sans cette règle, la fiche ne servirait à rien : un opérateur pressé tape les
cotes du plan, l'écran affiche « mesuré », et plus personne — lui le premier —
ne sait ce que les verdicts valent. Le projet interdit ailleurs d'annoncer
±0,02 mm comme acquis ; la même interdiction vaut pour 250 mm de bras.

### Onze cotes sont critiques, et ce ne sont pas « les plus importantes »

Ce sont celles dont **une erreur ne se voit pas à l'écran**. Une course fausse
fait refuser une passe, et cela se remarque. Un pivot faux de 1 mm laisse la
simulation parfaitement verte et décale la pièce de 1 mm.

`CRITIQUES` liste donc R, r, L, les deux butées de chariot et les six
coordonnées de pivot. Tant qu'elles ne sont pas mesurées, `DeltaLineaire.source`
dit « cotes PROVISOIRES » et la description de la machine dit « DESSINÉE ».

### Treize cotes sont réservées à la calibration

Un pivot ne se relève pas au pied à coulisse : il s'ajuste sur un cercle palpé.
`mesurer()` les **refuse** avec son motif ; `regler()` les accepte — on peut
vouloir essayer « et si le pivot était là ? » — mais les marque `ESSAI`.

Conséquence à l'écran : ces cotes n'ont **pas de champ « mesuré avec »**. En
proposer un laisserait croire qu'on peut les relever à la main, alors que la
fiche refuserait la mesure. Un champ qui n'aboutit jamais est un piège.

### La sécurité est une déclaration, jamais une commande

Les trois cotes du groupe sécurité (arrêt d'urgence, fins de course, capot) sont
**constatées**, pas pilotées. Cocher une case n'arrête aucune broche : ces
organes sont matériels et indépendants du logiciel par construction. Leur
absence remonte dans le résumé plutôt que d'y être passée sous silence.

### La fiche fait autorité, les réglages en sont une vue

`Session.fiche` est chargée du disque au démarrage et **enregistrée à chaque
saisie**, sans bouton « enregistrer » : une cote relevée sur la machine puis
perdue parce qu'on a fermé la fenêtre ne se remesure jamais.

`Reglages` reste, parce que les écrans existants le lisent, mais devient une
**vue en lecture** : `_fiche_vers_reglages` recopie dans un seul sens.
`REGLAGES_VERS_FICHE` fait la correspondance, écrite une fois et lue des deux
côtés — l'ancien écran de réglages écrit désormais **dans la fiche**.

Le fichier est un JSON **lisible à l'œil**, gardé hors du dépôt : il décrit un
exemplaire physique, pas le logiciel. Deux machines montées à partir du même kit
n'ont pas les mêmes cotes. `XYZAC_FICHE_MACHINE` permet d'en désigner un autre.

Au **rechargement**, seules la valeur et la provenance viennent du fichier ; les
libellés, les bornes et les phrases de mesure viennent du code. Une fiche
enregistrée il y a six mois profite donc des corrections apportées depuis, au
lieu de figer un texte faux.

## Défauts trouvés en conduisant la page au navigateur

Aucun ne se voyait autrement, et c'est le propos de cette épreuve :

1. **`.cote` était déjà pris** par le panneau de simulation. Ma règle CSS du même
   nom l'écrasait en silence. Renommée `fiche-cote`.
2. **La page était inatteignable** : la règle générale « sans pièce, retour à
   l'étape 1 » s'appliquait à l'écran qu'on ouvre justement avant d'avoir une
   pièce, le jour du montage.
3. **Le refus n'atteignait jamais l'écran.** `post()` ne lève pas sur un 400 : il
   rend le corps de la réponse. Le `try/catch` ne voyait donc rien, la fiche
   n'était pas redessinée, et la valeur absurde disparaissait **sans un mot**.
4. **La pastille de provenance s'affichait sans fond** : la couleur vient d'une
   règle descendante (`.faisable .pastille`), donc la classe d'état va sur un
   ancêtre. Posée sur la pastille, elle ne s'appliquait pas ; posée sur la ligne
   de titre, elle traînait avec elle un `border-left` prévu pour un `<li>`. Elle
   vit maintenant sur un `<span>` qui ne sert qu'à ça.
5. **La fiche de l'épreuve atterrissait dans le dossier du logiciel** et devenait
   le point de départ de l'épreuve suivante, qui n'essayait alors plus ce
   qu'elle croyait essayer.

Un défaut trouvé par le test unitaire, aussi : **dix-neuf phrases de mesure
étaient des raccourcis** (« Même méthode », « Voir Pivot C — X »), inutilisables
à quelqu'un debout devant la machine. Le test exige plus de 40 caractères, ce
qui est grossier mais suffit à attraper la paresse.

## Ce que cela ne fait pas

- La fiche **ne pilote rien**. Elle décrit une machine ; le reste du logiciel
  s'en sert pour simuler.
- Elle ne vérifie pas la **cohérence** entre cotes : rien n'interdit encore de
  déclarer des bras plus courts que R − r, ce qui donnerait une delta qui ne
  peut pas exister.
- Elle ne **date pas la validité** d'une mesure : une cote relevée il y a un an
  sur une machine démontée depuis porte sa date, mais personne ne la compare à
  rien.
- Les cotes `ESSAI` et `MESURE` sont traitées **de la même façon par les
  calculs** — seule leur présentation diffère. C'est voulu à ce stade : le
  moteur calcule avec ce qu'on lui donne, et c'est l'écran qui dit ce que ça vaut.
