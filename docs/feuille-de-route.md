# Feuille de route — du logiciel à la machine

> État au 19 septembre 2026. Ce document dit **ce qui est fait et mesuré**, **ce
> qui reste**, et dans quel ordre. Il ne promet aucune date : le rythme dépend
> de la machine, qui n'existe pas encore.

## Où on en est

Le logiciel sait, aujourd'hui, et c'est **mesuré sur les 20 pièces du corpus** :

- **lire une pièce** STEP et en tirer ses surfaces ;
- **trouver les creux** — 23 sur le corpus — et, pour chacun, le plus gros outil
  qui atteint son fond, la reprise qu'il faut derrière, et l'orientation A/C
  depuis laquelle il s'attaque. Quand ça ne passe pas, il nomme **laquelle des
  trois étapes bloque** et le geste qui la lèverait ;
- **vérifier une orientation** en entier : porte-outil, nez de broche, organes
  machine, butées d'axes, courses linéaires — y compris la cinématique **delta**,
  testée exactement segment par segment, sans échantillonnage ;
- **simuler** l'enlèvement de matière et **chiffrer le temps de cycle** comme un
  plancher déclaré ;
- **porter la fiche de la machine** : 46 cotes, chacune avec ce qu'elle change,
  comment la mesurer, et d'où elle vient.

Ce qu'il ne fait pas, et ne prétend pas faire : **piloter quoi que ce soit**.
Aucune commande ne sort. L'interface est marquée SIMULATION UNIQUEMENT.

## Ce qui reste, dans l'ordre

### Phase A — pendant que la machine se construit *(rien ne dépend du matériel)*

| # | Chantier | Pourquoi maintenant |
|---|---|---|
| A1 | **Le fraisage en roulant** (flanc de l'outil) | 3 creux du corpus reçoivent « au flanc seulement » — un aveu du moteur, pas un refus de la pièce. C'est le plus gros trou fonctionnel restant. |
| A2 | **Plusieurs orientations par creux** | Une poche a un fond et quatre flancs. On ne décide aujourd'hui qu'une orientation, et on compte les points qui regardent ailleurs sans les traiter. |
| A3 | **La trajectoire elle-même** | On sait *quel outil, depuis où*. On ne sait pas encore *quel parcours*. C'est ce qui sépare un analyseur d'un vrai CAM. |
| A4 | **Le transport (71 % du temps de cycle)** | Mesuré : 140 838 mm de rapides, 1 197 dégagements, 24 à 29 % du temps seulement en coupe. Le plus gros levier chiffré du projet, pas commencé. |
| A5 | **Détail plus fin que la grille** | Sur C20 la gravure disparaît à 1 mm de pas et l'atelier répond « aucun creux » — vrai à cette résolution, faux pour la pièce. Il faut le **dire**, en comparant le volume voxélisé au volume B-Rep. |
| A6 | **Organes de collision de la delta** | Colonnes, anneau, bras balayés : aucun n'est modélisé. Sur une delta, ce sont les bras qui touchent en premier quand la pièce est haute. |
| A7 | **Carte de rigidité** | Une delta n'a pas la même raideur partout dans son volume. Aucun chiffre aujourd'hui. |
| A8 | **Post-processeur LinuxCNC** + son module de cinématique delta+AC | À écrire et à **valider hors machine**, contre le simulateur. LinuxCNC reste la seule couche autorisée à exécuter du mouvement. |

### Phase B — le jour où la machine existe *(dans cet ordre, il n'est pas négociable)*

Cet ordre est celui de `assembly_calibration`, et chaque étape suppose la
précédente franchie.

| # | Étape | Ce qu'on en tire | Simulable ? |
|---|---|---|---|
| B1 | Test de câblage | continuité, phases, fins de course | **non** |
| B2 | Sens des axes | le piège n° 1 du montage | **non** |
| B3 | Prise d'origine | répétabilité — 10 prises, on garde l'**étendue** | oui (méthode) |
| B4 | Courses réelles | les vraies butées, pas celles du plan | **non** |
| B5 | Équerrage, planéité | géométrie | oui (méthode) |
| B6 | Jeux | par inversion, axe par axe | oui (méthode) |
| B7 | **Pivots A et C** | **les 6 cotes critiques** | oui (méthode) |
| B8 | Palpeur | rayon effectif, excentration | oui (méthode) |
| B9 | Caméra | si caméra il y a | **non** |
| B10 | **Pièce d'épreuve** | usinée **puis mesurée sur un moyen indépendant** | **non** |

**B10 est la seule étape qui transforme ±0,02 mm d'objectif en fait.** Tant
qu'elle n'est pas franchie, la tolérance reste un objectif, et l'atelier l'écrit.

### Phase C — après la qualification

- **Reprise en seconde prise** (retournement) : simuler le remontage.
- **5 axes simultané** : aujourd'hui le moteur décide le 3+2, positivement comme
  négativement, et rien de plus.
- **Collision sur les segments coupants** : 22 ms par sommet, soit ~8 min pour
  un parcours d'ébauche. Praticable seulement après A3 et A4.

## Ce qu'il faut de vous, et quand

1. **Maintenant** — les **cotes du châssis** dès que le dessin est figé : R, r, L,
   course des chariots. Elles sont dans la fiche avec la méthode de mesure ; tant
   qu'elles viennent du plan, elles sont marquées « du plan ».
2. **Au montage** — la fiche machine, groupe par groupe. Comptez une demi-journée
   pour les cotes au pied à coulisse, une journée pour la calibration palpée.
3. **Avant toute coupe** — les trois déclarations de sécurité. Elles sont
   **matérielles** : cocher la case ne fait rien, elle constate.

## La règle qui ne bouge pas

> Le logiciel ne pilote jamais les moteurs. Toute trajectoire passe par
> `collision_engine` + `kinematics_solver` + `simulation_engine` +
> `safety_state_machine`. Une modification du montage invalide l'approbation.
> L'arrêt d'urgence et les interlocks sont **matériels et indépendants**.
> LinuxCNC est l'unique couche autorisée à exécuter du mouvement réel.
