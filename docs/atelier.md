# L'Atelier — l'interface de l'utilisateur

## 1. Ce que c'est, et ce que ce n'est pas

Le **banc de debug** (`docs/banc-de-debug.md`) montre ce que le moteur
*calcule*. L'**atelier** montre ce que l'utilisateur *doit faire*. Ce ne sont
pas deux présentations du même écran : l'un sert à trouver un défaut, l'autre à
décider.

Et il sert d'abord à **décider de la mécanique avant de la construire** : les
cotes que vous n'avez pas encore coulées dans le métal — courses, débattement
de la bascule A, rayon du plateau, outil — sont des champs modifiables. Changez
une cote, relancez, regardez ce que cela change sur une vraie pièce. C'est ce
que la simulation permet de faire à ce stade, et c'est ce qui coûte le plus
cher à découvrir après.

> **SIMULATION UNIQUEMENT.** Aucune machine n'est reliée à cette fenêtre. Un
> test vérifie, sur l'AST de tous les modules de l'atelier, qu'aucun n'importe
> `linuxcnc_gateway`, `socket`, `serial` ou `linuxcnc`. Le serveur n'écoute que
> sur la boucle locale.

## 2. Lancer

**Double-cliquez** sur `demarrer-atelier.bat` (Windows) ou
`demarrer-atelier.command` (macOS / Linux). En ligne de commande, c'est le même
fichier :

```bash
python tools/demarrer_atelier.py
```

Il trouve Python, crée un `.venv` à côté du logiciel, installe `[atelier]` si
nécessaire, fabrique les exemples s'ils manquent, puis démarre. La première fois
demande environ **300 Mo** de bibliothèques — mesuré sur une installation neuve,
pas estimé ; les suivantes sont immédiates. Effacer le dossier `.venv` annule
tout, sans rien laisser ailleurs.

Les deux lanceurs ne portent **aucune** logique : un `.bat` ne s'éprouve pas
sur une machine Linux, un `.command` ne s'éprouve pas sur Windows, et s'ils
installaient eux-mêmes, la moitié de ce que reçoit l'utilisateur ne serait
jamais essayée. Ils trouvent Python et passent la main au script Python, qui
est le même partout. Un test le vérifie.

À la main, si vous préférez :

```bash
pip install -e ".[atelier]"
python -m xyzac.ui.atelier
```

`[atelier]` et non `[ui]` : le serveur est en bibliothèque standard et les vues
sont rendues hors écran, donc Qt n'y sert à rien — c'est ~200 Mo qu'un
Raspberry Pi n'a aucune raison de porter.

L'atelier **contrôle le rendu 3D au démarrage**, par une vraie image de 32 × 32
pixels et non par un `import` : un import qui réussit ne dit pas qu'une image
sortira, et sur un Pi sans écran c'est le pilote qui manque, pas la
bibliothèque. S'il ne peut pas rendre, il le dit dans le terminal **et sur la
page**, avec la commande à taper. Avant, la panne arrivait à la première vue,
sous la forme d'une image vide muette et d'une trace visible du seul terminal.

Le navigateur s'ouvre sur `http://127.0.0.1:8765/`. `Ctrl+C` pour arrêter.

Pas de navigateur (Pi en SSH) : `--sans-navigateur`, puis ouvrez l'adresse
depuis votre poste avec un tunnel `ssh -L 8765:127.0.0.1:8765 pi@…`.

## 3. Les cinq étapes

1. **Votre pièce** — glissez votre fichier `.step` ou `.stp` sur la page, ou
   choisissez-le avec le bouton. Clé USB, pièce jointe, dossier de CAO : le
   fichier passe par l'importeur **contrôlé** du moteur, celui qui refuse une
   coque non fermée en disant pourquoi. Vous n'avez pas encore de fichier ? Un
   volet replié prête 20 géométries d'exemple, plus 3 volontairement abîmées —
   voir ce que le logiciel fait d'un mauvais fichier vaut mieux que le
   découvrir avec le sien.
2. **Regardez** — la pièce sur le plateau, dans la machine. Quatre boutons
   pour tourner la vue.
3. **Cette machine peut-elle faire cette pièce ?** — le moteur essaie les six
   façons de poser la pièce et répond **surface par surface**, chaque surface
   nommée par ce qu'on peut montrer du doigt (« le dessous », « le flanc
   droit ») et chaque verdict assorti d'une action. Un volet replié,
   *« ma machine n'a pas ces cotes »*, donne les neuf réglages : ce sont ceux
   qui changent l'**accessibilité**, les avances changent le temps d'usinage
   et pas la faisabilité.
4. **Regardez-la s'usiner** — voir §3bis.
5. **Lancer** — voir §3ter.

Les étapes 2 à 5 restent grisées tant qu'aucune pièce n'est chargée, et disent
pourquoi. Un bouton qui ne répond pas est pire qu'un bouton absent.

### 3bis. La simulation d'usinage

Ce n'est **pas** un tour de manège autour de la pièce. La caméra ne bouge pas ;
c'est l'outil qui parcourt la trajectoire que `plan_roughing` a réellement
calculée, avec les A/C que ce plan a choisis, et la trajectoire déjà parcourue
se dessine derrière lui. Sous chaque image : X, Y, Z, A, C de la pose, si
l'outil coupe ou se déplace en rapide, et **s'il sort des courses réglées** —
ce dernier point a trouvé un cas réel dès le premier essai (plan de dégagement
à Z = 62 mm pour une course qui s'arrête à 60).

Ce que la simulation **ne** montre **pas**, et qu'elle écrit sous elle, chiffré
depuis l'état réel :

- les passes de **finition** — seule l'ébauche est calculée ;
- la **matière qui disparaît** — la pièce finie est dessinée dès la première
  image ;
- les **brides**, qui ne sont modélisées nulle part dans le projet ;
- la matière restante, séparée en deux : celle qu'**aucune** indexation
  candidate ne voit (il faut reposer la pièce) et celle que l'aperçu laisse
  parce qu'il **se limite à 2 indexations** pour tenir en quelques secondes.

### 3ter. Le bouton LANCER

Il ne fait pas partir la machine, et **aucun bouton de ce logiciel ne le
fera** : déposer un fichier programme puis laisser l'opérateur l'ouvrir et
appuyer garde un humain dans la boucle au dernier moment, celui où l'on regarde
la machine avant qu'elle bouge.

Ce qu'il fait : il affiche les **quatre conditions** à remplir, et ce qu'il faut
faire pour chacune. Aujourd'hui les quatre sont non remplies, parce qu'une
machine en kit qu'on vient d'assembler n'a ni gamme approuvée ni dossier de
calibration. C'est exact, et il n'y a aucune raison de l'habiller.

Ces conditions ne sont **pas** écrites dans l'interface. Elles viennent de
`xyzac/production_gate.py`, c'est-à-dire du même endroit que celui où
`linuxcnc_gateway.deposit` les fait respecter en refusant. Écrites deux fois,
elles auraient fini par diverger — et la copie divergente aurait été celle
qu'on lit à l'écran, donc celle sur laquelle quelqu'un se serait fié. Un test
(`test_the_page_and_the_deposit_refuse_for_the_same_reasons`) les attache
l'une à l'autre.

## 3quater. Le design, et pourquoi il est clair

Retouche complète après un premier jet jugé « vraiment moche », et le reproche
était mérité : cinq cartes identiques empilées, tout au même poids
typographique, et une vue 3D sombre dans laquelle le porte-outil était une
tache noire sur un fond noir.

**Thème clair.** Le banc de debug est sombre et doit le rester : son dégradé
d'outil encode la gravité d'un contact, du clair (l'arête, qui *doit* toucher)
au sombre (le nez de broche, qui ne doit *jamais* toucher). Sur fond noir, les
deux extrémités de ce dégradé disparaissent. Un atelier se regarde de jour,
souvent debout ; les logiciels de CAO sont clairs, ce qui évite à l'œil de
changer de régime entre deux fenêtres. Seul le **fond** de la vue est réglable
(`capture(background=…)`) : le code couleur reste l'unique source.

**Une légende sous chaque vue**, parce que rien ne disait « bleu = le brut ».
Une image qu'il faut se faire expliquer n'informe pas. Les teintes viennent de
`ui.debug.palette` par le serveur : les recopier dans la feuille de style aurait
créé une deuxième vérité, et c'est la copie *affichée* qui aurait menti. Un test
interdit toute teinte en dur dans `style.css` et `app.js`.

**Un fil d'étapes** collant en haut, où une étape est « faite » quand ce qu'elle
produit *existe* — pas quand on l'a cliquée : un bouton pressé dont le calcul a
échoué n'a rien fait.

**Le même cadrage à l'étape 2 et à l'étape 4.** Le cadrage « machine »
englobait tout le volume de courses (300 × 240 × 180 mm), ce qui rendait une
pièce de 60 mm minuscule dans une cage en fil de fer — et la vue ne ressemblait
pas à celle de la simulation, alors que c'est la même scène. L'opérateur avait
deux images à réconcilier au lieu d'une à comprendre.

### 3quinquies. Le rendu de la vue 3D

Quatre changements, chacun décidé en comparant deux images plutôt qu'en
raisonnant :

- **Éclairage « light kit »** — trois sources et un remplissage. Sans lui la
  scène est plate : un dôme n'a plus de dôme, un porte-outil est une tache.
- **Anti-crénelage SSAA.** Les arêtes en escalier sont ce qui fait qu'une image
  « a l'air d'un logiciel ». Coût mesuré : **0,67 s par image** contre 0,42 s
  sans, soit environ dix secondes de plus sur une simulation de 36 images.
- **Réflexion spéculaire, et non PBR**, alors que le PBR est plus moderne.
  Mesure sur les deux images : le PBR fait virer l'ambre de la pièce vers
  l'olive et le gris du brut vers le brun, parce qu'il *recalcule* la couleur.
  Or ces teintes portent une signification, et une signification qui change de
  couleur selon l'angle de la caméra ne signifie plus rien. Le spéculaire
  ajoute un reflet **sans toucher à la teinte**.
- **Les liaisons au second plan** (opacité 0,28). Mesure : 1 615 remontées et
  descentes pour 12 700 segments de coupe. Au même poids que la coupe, elles
  formaient une palissade verticale qui cachait la pièce qu'on venait
  regarder. Elles restent visibles — ce sont elles qui portent les mouvements
  qui traversent la pièce quand ils sont mal générés.

Et le cadrage est **resserré de 1,6** : le cadrage porte sur les organes
machine, ce qui le rend stable à toute indexation A/C, mais le plateau et le
berceau sont bien plus grands qu'une pièce de kit. Vérifié sur les **20 pièces
du corpus** : zéro pixel de pièce au bord de l'image.

Le resserrage rapproche la caméra de son point visé, et n'emploie *pas*
`plotter.camera.zoom()` — mesure : `zoom()` agit sur l'angle de vue, que
`camera_position` ne transporte pas, donc le paramètre était sans effet et deux
cadrages différents rendaient deux images identiques au pixel. Un test le
verrouille.

## 4. Trois décisions de construction

**Serveur : bibliothèque standard de Python.** Pas Flask, pas FastAPI. Cet
outil doit démarrer sur le Raspberry Pi d'un acheteur de kit, en une commande,
sans rien installer de plus. Une dépendance de serveur web se paie à chaque
mise à jour, pour un service que `http.server` rend ici très bien.

**Vue 3D calculée côté serveur, envoyée en image.** Marche sans pilote
graphique — donc sur un Pi sans écran comme sur un portable — et sans charger
de bibliothèque 3D dans le navigateur.

**Le fichier téléversé arrive en corps brut, son nom dans un en-tête.** Pas de
`multipart/form-data` : l'analyser correctement demande soit une dépendance,
soit une centaine de lignes, pour transporter une seule chose que le corps brut
transporte tel quel. La taille est vérifiée sur `Content-Length` **avant**
lecture — mesurer après avoir lu laisserait n'importe quel envoi remplir la
mémoire du Pi. Le nom est reconstruit caractère par caractère côté serveur :
il vient de la machine de quelqu'un d'autre et n'a aucune raison d'être sain.

**La page ne demande rien au réseau.** Aucune balise ne pointe vers un domaine
extérieur, l'icône est en ligne dans le HTML. Elle fonctionne hors ligne, et un
test le vérifie.

## 5. La traduction est un travail, pas du décor

Le moteur dit `AXIS_LIMITS 24/24`. L'atelier dit : *« la bascule A ne va pas
assez loin pour présenter cette surface : il faut retourner la pièce »*. C'est
la même information et ce n'est pas le même lecteur.

Mais la traduction **n'ajoute rien** : chaque phrase correspond à un champ
calculé par le moteur, jamais à une appréciation. Et un test structurel exige
que **tout** motif de blocage que le moteur sait produire ait sa consigne —
sinon l'utilisateur reçoit un constat sans suite, la seule chose qu'une
consigne ne doit jamais faire.

Un exemple de ce que cela a coûté : le premier jet affichait, pour les deux
plus grandes surfaces du dôme, « le moteur ne sait pas trancher ici :
l'échantillonnage est trop grossier pour ce diagnostic ». Exact, et inutile.
La version actuelle donne toujours le motif principal du solveur — donc une
action — et mentionne l'indécision comme une réserve, à sa place.

## 6. Ce que l'atelier dit toujours de son propre résultat

- le verdict est établi sur **6 points sondés par surface** : il écarte, il ne
  garantit pas ;
- **aucun bridage n'est modélisé** : un bridage réel retire des orientations,
  donc le résultat est **optimiste** ;
- dès qu'il y a plus d'un montage : chaque remontage repositionne la pièce et
  **les erreurs s'additionnent** — aucune tolérance ne peut être annoncée d'un
  montage à l'autre.

## 7. L'éprouver

```bash
python -m pytest tests/test_ui_atelier.py -q        # session, serveur, langage
python tools/test_atelier_navigateur.py             # la page, dans un navigateur
```

Le second demande `playwright` et un navigateur, ce qui explique qu'il vive
dans `tools/` : il ne doit pas alourdir la suite du projet. Il clique
réellement sur les boutons, attend les images, lit les verdicts, et laisse ses
captures dans `out/atelier/`.

Résultat de la dernière exécution : fichier `.step` **téléversé** par le
sélecteur (60 × 60 × 25 mm, annoncé « votre fichier »), un `.txt` **refusé** en
clair, puis le dôme C10 chargé depuis les exemples, vue tournée, réglage
changé, **verdict en 46 s** — 4 surfaces usinables telles quelles, 1 après
retournement, 3 à changer —, **simulation d'usinage de 36 images** sur
22 587 points de trajectoire en 2 opérations d'ébauche (79 % de la matière
enlevée), lecture, pose d'axes affichée sous chaque image, puis les 4
conditions de lancement, toutes non remplies. **Aucune erreur dans la
console.**
