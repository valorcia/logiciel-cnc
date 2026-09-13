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

```bash
python -m xyzac.ui.atelier
```

Le navigateur s'ouvre sur `http://127.0.0.1:8765/`. `Ctrl+C` pour arrêter.

Pas de navigateur (Pi en SSH) : `--sans-navigateur`, puis ouvrez l'adresse
depuis votre poste avec un tunnel `ssh -L 8765:127.0.0.1:8765 pi@…`.

## 3. Les cinq étapes

1. **Choisissez une pièce** — 20 géométries d'exemple, plus 3 volontairement
   abîmées : voir ce que le logiciel fait d'un mauvais fichier vaut mieux que
   le découvrir avec le sien.
2. **Regardez** — la pièce sur le plateau, dans la machine. Quatre boutons
   pour tourner la vue.
3. **Réglez votre machine** — neuf cotes. Ce sont celles qui changent
   l'**accessibilité** ; les avances changent le temps d'usinage, pas la
   faisabilité, et les mélanger ferait croire qu'elles se valent.
4. **Cette machine peut-elle faire cette pièce ?** — le moteur essaie les six
   façons de poser la pièce et répond **surface par surface**, chaque surface
   nommée par ce qu'on peut montrer du doigt (« le dessous », « le flanc
   droit ») et chaque verdict assorti d'une action.
5. **Simulez** — un tour complet autour de la scène.

## 4. Trois décisions de construction

**Serveur : bibliothèque standard de Python.** Pas Flask, pas FastAPI. Cet
outil doit démarrer sur le Raspberry Pi d'un acheteur de kit, en une commande,
sans rien installer de plus. Une dépendance de serveur web se paie à chaque
mise à jour, pour un service que `http.server` rend ici très bien.

**Vue 3D calculée côté serveur, envoyée en image.** Marche sans pilote
graphique — donc sur un Pi sans écran comme sur un portable — et sans charger
de bibliothèque 3D dans le navigateur.

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

Résultat de la dernière exécution, sur le dôme C10 avec les cotes du kit :
page chargée, pièce importée (60 × 60 × 44 mm), vue tournée, réglage changé,
**verdict en 41 s** — 4 surfaces usinables telles quelles, 1 après
retournement, 3 à changer —, simulation de 24 images, lecture. **Aucune erreur
dans la console.**
