# ADR-011 — Jalon M11 : ordonnancer plusieurs **montages**

## 1. Le trou que M11 comble

Depuis M10 le moteur sait dire, **sur la passe entière**, qu'une face est
inatteignable — et il nomme le remède. Sur le dôme C10, quatre passes sur huit
rendaient `AXIS_LIMITS` avec pour remède « cette face demande un second
montage ». Le verdict était juste et **personne ne l'ordonnançait** : le plan
s'arrêtait sur un constat.

---

## 2. Décisions

### D94 — Un remontage est une **rotation du repère pièce**, rien de plus

Le champ d'obstacles ne contient que la pièce, le brut et les bridages — tout
ce qui tourne **avec** la pièce ; les organes machine sont traités à part par
`MachineGuard`. Il suffit donc de faire tourner le champ, les points de passe
et leurs normales. **Aucune modification du solveur**, et l'équivalence avec un
remontage physique est exacte plutôt qu'approchée.

### D95 — **Six** candidats, et non vingt-quatre

Le cube a 24 rotations. Mais l'axe C de cette machine est **continu** : deux
montages qui ne diffèrent que par une rotation autour du Z du montage sont **le
même montage**, la machine faisant la différence toute seule. Ne restent que
les six choix de la face posée sur le plateau.

C'est la **cinématique de la machine** qui réduit l'espace de recherche, pas
une heuristique — et c'est le genre de réduction qu'on n'obtient qu'en
raisonnant sur la machine réelle plutôt que sur un problème générique.

### D96 — Un booléen « atteignable » confond deux questions

1. **ce montage** présente-t-il cette surface à l'outil ?
2. l'**outil** rentre-t-il dans cette surface ?

La première dépend du montage ; la seconde n'en dépend pas du tout, puisque le
champ tourne avec la pièce. Le discriminant est une **machine idéale** — toutes
les directions permises : si le point échoue encore, aucun montage n'y changera
rien.

Sans cette séparation, le plan renvoyait à « revoir l'outil ou le bridage ».
Avec elle, il dit : *retournée, la passe 1 n'a qu'un point de sondage en échec
sur huit, et pour cause d'arête de coupe — le retournement ouvre la face, c'est
l'outil qui bloque.* Deux décisions différentes, deux interlocuteurs
différents.

### D97 — Le test décidable est « un outil **deux fois plus fin** », pas « un outil ponctuel »

La première version testait les points durs avec un bec de 0,1 mm, pour
conclure « aucun rayon de bec ne lève ce point, donc c'est la géométrie ». La
mesure a démoli ce raisonnement : le champ est gonflé d'au moins **1,26 mm** au
pas d'échantillonnage courant, soit **douze fois** le rayon du bec sondé. Un
tel outil est bloqué par le gonflement seul, et son échec ne prouve rien — au
pas de 0,5 mm, le même point devient atteignable.

**Troisième apparition de la même faute dans ce projet** : une grandeur dominée
par une autre, et lue comme si elle mesurait ce qu'on voulait. La marge du
certificat de gouge en M6 ; la marge tous tronçons en M10 ; le bec de sondage
ici.

Le test est donc : *un outil réellement plus petit — moitié de diamètre —
lève-t-il ces points ?* La réponse est actionnable, et `probe_conclusive`
refuse de répondre quand le bec de sondage ne dépasse pas le gonflement. La
question du rayon nul reste **ouverte**, parce que le test discret ne sait pas
décider au-dessous de son propre gonflement (ADR-001 / D2).

### D98 — La machine et l'outil sont passés **explicitement**

`make_solver(field, mount, machine, tool)`. Le dépistage emploie deux machines
— la vraie et l'idéale — et jusqu'à deux outils. Cachées dans une clôture,
elles ne pourraient pas être remplacées, et le diagnostic se réduirait au
booléen que D96 récuse.

### D99 — Le glouton est assumé, et le résidu est **nommé**

Couverture d'ensembles, donc NP-difficile ; avec six candidats et une dizaine
de passes, l'optimum n'a aucun intérêt pratique. À égalité, « tel quel »
d'abord : un remontage évité vaut mieux qu'un remontage arbitrairement
équivalent — mais la préférence n'écrase jamais une **meilleure** couverture.

Pour chaque passe non couverte, le plan dit le meilleur montage trouvé, la part
atteignable, et le partage **exclusif** entre ce qui tient au montage, ce qu'un
outil plus fin lèverait, et ce qu'il ne lèverait pas.

### D100 — Un montage de plus ne se paie pas en temps

Chaque remontage **reréférence** la pièce : palpage propre, incertitude propre,
et les budgets **se composent**. Une cote entre deux surfaces usinées dans deux
montages différents porte l'erreur des deux repérages plus celle du transfert.

Le moteur ne sait pas encore chiffrer cette composition — il faudrait modéliser
le transfert d'origine, ce qui n'est pas fait. Il **refuse donc d'annoncer un
chiffre**, et dit pourquoi. `tolerance_statement()` du dossier de calibration
reste le seul endroit autorisé à énoncer une précision, et elle ne vaut que
dans un montage.

---

## 3. Ce que la mesure a donné, et ce qu'elle a corrigé

Dôme C10, outil hémisphérique Ø6, six montages dépistés en **55 s** :

| | |
|---|---|
| Montage retenu | « tel quel » — passes 4, 5, 6, 7 |
| Passe 0 | au mieux 88 % (« tel quel ») ; 1 point qu'un outil deux fois plus fin ne lève pas |
| Passe 1 | au mieux 88 % (**« retourné »**) ; idem |
| Passe 2 | au mieux 88 % (**« retourné »**) ; 1 point qu'un outil plus fin lèverait |
| Passe 3 | au mieux 75 % ; 1 point qu'un outil plus fin lèverait, 1 qu'il ne lèverait pas |

**Ce que cela corrige de M10.** Le remède « cette face demande un second
montage » était juste pour les passes 1 et 2 — le retournement les ouvre — et
il s'arrêtait trop tôt : après le retournement, ce qui reste n'est plus une
question de montage mais d'**arête de coupe**. Quatre passes déclarées
« définitivement rejetées » sont en réalité atteignables à 75–88 %, et le
résidu se compte en un ou deux points.

**Un résultat contre-intuitif**, trouvé en écrivant les tests : deux faces
opposées ne demandent pas forcément deux montages. Couchée sur le côté, elles
deviennent toutes deux latérales et l'inclinaison A les présente ensemble. Le
test avait d'abord été écrit avec l'attente naïve, et c'est elle qui était
fausse.

---

## 4. Une faute d'architecture corrigée au passage

`BenchState.suggested_mount` calculait où poser la pièce sur le plateau — de la
**logique métier dans l'interface**, ce que la règle du projet interdit
explicitement. Le calcul vit maintenant dans `strategy_planner.setups`, et
l'interface délègue. Le garder en double aurait garanti qu'un jour les deux
divergent, comme `JOINT_AXIS` et la liste des blocs au jalon M9.

---

## 5. Ce que M11 ne lève pas

| | |
|---|---|
| **Bridages** | le banc n'en connaît pas, et un bridage réel retire des orientations. Une couverture obtenue sans bridage est **optimiste**, et le plan le dit |
| **Transfert d'origine** | non modélisé : aucune tolérance ne peut être annoncée d'un montage à l'autre (D100) |
| **Ordre des montages** | le plan donne un ensemble, pas une séquence. Quelle face usiner d'abord dépend de la rigidité et des appuis restants, que le moteur ne modélise pas |
| **Dépistage → verdict** | un dépistage à 8 points est **optimiste** ; une passe dépistée atteignable reste à vérifier en entier par `decide_indexed_pass` |
| **La question du rayon nul** | indécidable par le test discret au-dessous de son gonflement (D97) |
