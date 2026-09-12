# ADR-008 — Jalon M8 : un programme exécutable

- **Statut** : Accepté (jalon M8)
- **Date** : 2026-09-12
- **Contexte** : complète ADR-001 à ADR-007.

---

## 1. Ce que M8 apporte

M7 avait levé la moitié logicielle du verrou du post-processeur : la géométrie
se mesure, les erreurs se compensent, le G-code sort dans un fichier. Mais deux
trous rendaient ce fichier **inexécutable**, et ils n'étaient pas des détails :

- **aucune avance qualifiée.** L'émetteur écrivait `F300` par défaut. Un nombre
  inventé dans du code livré, exactement ce que ce projet refuse partout
  ailleurs.
- **ni approche ni dégagement.** Le chemin commençait au premier point de coupe
  et finissait au dernier. Un contrôleur qui reçoit cela amène l'outil au
  premier point par un mouvement non décrit — au mieux depuis la position
  courante, en ligne droite à travers la pièce — puis le laisse dans la matière.

| Limite M7 | Traitement M8 | État |
|---|---|---|
| Avances et vitesses non qualifiées | `recipe_profiles` implémenté ; l'émetteur **refuse** d'inventer | **levée** |
| Approche et dégagement non générés | portés par la trajectoire, et validés comme le reste | **levée** |
| Machine non construite ni qualifiée | inchangé | **ouverte** |
| Envoi réel à LinuxCNC | `linuxcnc_gateway` verrouillé | **ouverte, volontairement** |

---

## 2. Décisions

### D66 — Aucune interpolation entre matières : une matière inconnue lève

`UnknownMaterialError` plutôt qu'un repli sur la matière voisine de table.
Usiner de l'inox avec des paramètres d'aluminium casse l'outil au premier
engagement, et une table qui devine est plus dangereuse qu'une table qui
refuse.

### D67 — Les valeurs sont des points de départ, avec leur source et leur incertitude

Chaque matière porte sa provenance (« pratique courante fraisage alu sur
machine légère ») et sa bande (`±50 %`). Ce ne sont **pas** les données d'un
fabricant pour un outil précis, et le dire fait partie du résultat.
`CuttingRecipe.qualified` vaut **False**, toujours : le logiciel ne peut pas
qualifier une chaîne mécanique assemblée par l'acheteur.

### D68 — La charge est déclassée par défaut, et le coefficient est rapporté

Défaut de ma première version : la table livrait ses valeurs accompagnées d'une
note disant « commencer nettement en dessous ». **Une note qui contredit la
valeur qu'elle accompagne ne protège personne** — c'est la même faute qu'un
silence documenté.

La charge est donc ramenée à **50 %** par défaut — profondeur, engagement et
avance par dent —, le coefficient et sa raison figurent dans la recette et dans
l'en-tête du G-code, et le relever est une décision à prendre *après* une
qualification physique (ADR-007), pas avant.

### D69 — Diamètre effectif d'un bec rond

Une fraise hémisphérique engagée sur une profondeur `ap` inférieure à son rayon
ne coupe pas à son diamètre nominal mais sur une calotte de diamètre

```
D_eff = 2·√(D·ap − ap²)
```

Mesuré : à `ap = 0,2 mm`, une fraise de 6 mm coupe à **2,15 mm**. Appliquer la
vitesse de broche du diamètre nominal divise donc la vitesse de coupe réelle
par près de trois — l'outil frotte au lieu de couper, et s'use bien plus vite
qu'à la bonne vitesse. C'est l'erreur la plus courante en finition 5 axes, et
la plus invisible.

### D70 — Amincissement radial du copeau

Sous un engagement radial `ae` inférieur au rayon, l'épaisseur de copeau réelle
est plus faible que l'avance par dent programmée, dans le rapport
`D / (2·√(ae·(D − ae)))`, qui vaut 1 à `ae = D/2` et croît quand l'engagement
diminue. Ne pas le poser fait travailler l'outil en frottement — le mode de
destruction le plus courant en finition. Le facteur est borné à 4 : au-delà, le
modèle quitte son domaine, et multiplier l'avance par dix serait pire que de ne
rien corriger.

### D71 — Un bridage qui éloigne la vitesse de coupe de sa cible produit un avertissement

Cas réel de **cette** machine, et il est sévère. La broche du kit a un plancher
à 6 000 tr/min. Avec une fraise de 6 mm, l'acier doux se coupe alors à
**113 m/min au lieu des 40 visés** — presque le triple, ce qui brûle l'arête.

Ce n'est pas un plafonnement bénin mais une recette **hors domaine**. Un
`clamped` discret ne suffit donc pas : au-delà de 25 % d'écart, la recette émet
un `warning`, et l'émetteur le recopie dans l'en-tête du fichier, découpé pour
rester lisible dans un éditeur de contrôleur.

Conclusion que ce calcul livre gratuitement : **une broche 6 000–24 000 tr/min
ne peut pas couper l'acier avec des outils de 6 mm ou plus.** C'est une
propriété de la machine, pas un réglage à chercher.

### D72 — Le conseil de remède allait dans le mauvais sens

Rectification, et c'est la troisième affirmation de sens écrite par
plausibilité que la mesure démentit dans ce projet.

Le conseil disait : vitesse de coupe trop élevée → prendre un outil **plus
grand**. La broche étant bridée, `Vc = π·D·N/1000` **croît** avec le diamètre :
il faut donc un outil plus **petit**. La démonstration était sous les yeux —
passer de 6 à 12 mm faisait monter Vc de 113 à 226 m/min — et le texte disait
le contraire.

Le conseil rend maintenant un **chiffre actionnable** plutôt qu'une direction :
`D = 1000·Vc_cible/(π·N)`, soit 2,12 mm pour l'acier sur cette machine. Vérifié
par construction : une fraise de 2 mm y donne exactement 40 m/min, sans
avertissement.

### D73 — Approche et dégagement, et ils passent les mêmes portes

`with_approach_retract` encadre un chemin, dans le repère **indexé** où le plan
de dégagement est défini :

```
approche   : rapide au plan de dégagement au-dessus du premier point,
             rapide jusqu'à standoff au-dessus de lui,
             puis AVANCE TRAVAIL jusqu'au point
dégagement : avance travail de standoff, puis rapide au plan
```

Le dernier segment de l'approche est en avance travail et non en rapide : un
rapide qui finit exactement sur la surface n'a aucune marge pour une erreur
d'origine palpée, et c'est le mouvement qui casse les outils.

Un plan de dégagement situé sous la matière est **relevé**, pas obéi : l'obéir
ferait descendre l'approche depuis l'intérieur de la pièce.

Et ces mouvements sont du **mouvement** : un test les soumet au `SweepChecker`
contre le brut intact et vérifie qu'ils sont subdivisés, pas seulement testés à
leurs extrémités. L'en-tête du G-code affirme qu'ils sont validés comme le
reste ; ce test est ce qui autorise cette phrase.

### D74 — L'opération porte le chemin continu, pas les seuls points de coupe

Défaut trouvé en comblant D73, et il était plus grave que le trou qu'il
accompagnait : `plan_roughing` mettait dans l'opération le résultat de
`toolpath_points`, qui **écarte les liaisons** — parce que cette fonction sert
à la simulation d'enlèvement de matière, laquelle ne doit compter que la coupe.

Conséquence : **ce qui aurait été posté n'était pas ce qui avait été validé.**
La validation progressive reconstruit le chemin continu couche par couche et
voyait donc les liaisons, tandis que le plan ne les portait pas. Le
post-processeur reliait deux passes par une avance travail en ligne droite,
c'est-à-dire à travers la pièce — exactement la collision que M3 avait
diagnostiquée et corrigée dans le validateur.

L'opération porte désormais `continuous_path` plus l'approche, avec ses
indicateurs `is_rapid`. Mesure sur la poche C02 : 4 385 points dont 1 032
rapides, contre un chemin de coupe seul auparavant.

### D75 — L'émetteur refuse d'inventer une avance

`feed_mm_min=300.0` par défaut a disparu. Une opération sans avance propre
exige une recette ; sans elle, la génération est **refusée** avec un message
qui dit quoi faire. L'en-tête porte la recette, sa source, son incertitude, son
déclassement, ses bridages et ses avertissements.

### D76 — Une mention d'en-tête doit dépendre de ce que le plan porte

L'en-tête annonçait inconditionnellement « APPROCHE ET DEGAGEMENT NON
GENERES ». La phrase est devenue fausse le jour où les opérations ont porté
leurs liaisons — et un en-tête qui annonce un manque comblé est aussi trompeur
qu'un en-tête qui cache un manque réel.

La mention regarde donc les trajectoires : elle **nomme les opérations** qui
n'ont pas de liaisons, ou déclare qu'elles sont portées et validées. C'est la
même règle que celle du docstring du module — laisser une justification périmée
en place est plus trompeur que de ne rien écrire — appliquée au fichier produit.

---

## 3. Ce que M8 ne lève pas

| Limite | Pourquoi |
|---|---|
| **Machine non construite ni qualifiée** | la moitié physique du verrou, inchangée depuis M7 |
| Envoi réel à LinuxCNC | `linuxcnc_gateway` verrouillé, délibérément |
| Avances **qualifiées** | les recettes sont des points de départ à ±50 %. Seule une qualification physique peut les resserrer |
| Table des matières | six matières génériques. Un déploiement réel doit charger les données du fabricant de l'outil employé |
| Approche des opérations de **finition** | `plan_finishing` produit encore des passes sans liaisons : ses plans sont des maquettes (ADR-006 / D50), et les encadrer donnerait l'illusion d'un programme complet |
| Rampe de plongée, hélice, pré-perçage | non générés : une plongée verticale dans la matière pleine est acceptable en alu, pas en acier |
| Gorgeage, hybride, Pi 5 | inchangés |

**±0,02 mm reste un objectif de qualification physique.**

---

## 4. Le schéma, sixième jalon consécutif

M8 ajoute trois défauts, tous de la même famille :

- **une affirmation de sens inversée** (D72), la troisième du projet après le
  signe de la crête en M5 et les deux docstrings de M7. La mesure était
  disponible et contredisait le texte ;
- **une note qui contredit la valeur qu'elle accompagne** (D68) : « commencer
  nettement en dessous » livré avec les valeurs de table. Variante du silence
  documenté de M6 — l'information est là, elle ne protège de rien ;
- **une mention devenue fausse** (D76), et **un plan qui ne portait pas ce qui
  avait été validé** (D74). Les deux sont des désynchronisations : une phrase
  et un objet qui décrivaient un état antérieur du code.

Ce jalon suggère donc une addition à la règle : **toute phrase qui décrit un
manque doit être calculée depuis l'état réel, pas écrite.** Une justification
écrite à la main vieillit sans prévenir ; celle qui regarde les données vieillit
avec elles.
