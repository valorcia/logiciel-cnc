# Référence : la landing page Xmachine WM-100 (xhorse3d)

Analyse de <https://xmachine.xhorse3d.com/>, relevée le 8 novembre 2026.

**Méthode.** Page ouverte dans Chromium (Playwright), à 1440 px et à 390 px de large.
Toutes les couleurs, tailles de police et hauteurs citées ici sont lues dans
`getComputedStyle` sur la page réelle, pas estimées à l'œil. Captures plein écran
dans `docs/reference-xmachine/` :

| Fichier | Contenu |
|---|---|
| `desktop-1440-full.png` | page entière à 1440 px (réduite à 640 px de large pour le poids) |
| `desktop-1440-hero.png` | premier écran à 1440 × 900 |
| `mobile-390-full.png` | page entière à 390 px |
| `mobile-390-hero.png` | premier écran à 390 × 844 |

**Chiffres de cadrage.** La page fait **30 344 px de haut en desktop** (≈ 34 écrans de
900 px) et **25 571 px en mobile**. C'est une page unique, sans navigation, sans menu,
sans en-tête collant, sans pied de page structuré. La seule chose qu'on puisse y faire
est cliquer un bouton vert qui part sur Kickstarter.

> Note technique : le site est construit sur **KickoffLabs** (thème
> `contest_box_waitlist_page`), un outil de page d'attente. Les images sont servies par
> `cdn.shopify.com` et `b.kickoffpages.com`. Le thème prévoit un formulaire de capture
> d'e-mail — **il n'y en a aucun sur la page** : zéro `<input>`, zéro `<form>`. Tout le
> trafic est renvoyé vers Kickstarter ou vers `preorder.xhorse3d.com`.

---

## 1. Ce que le site vend, à qui, à quel prix

**Le produit.** Une fraiseuse CNC **5 axes simultanés de bureau**, la **Xmachine WM-100**
de Xhorse3D (marque incubée par Xhorse, serrurerie/clés automobiles, fondée en 2010).
Vendue avec son logiciel de FAO, **XMakerHub**, présenté comme une FAO « pilotée par IA ».

**La cible.** Le texte vise trois publics en même temps, sans jamais trancher :
makers/hobbyistes (« Whether you're a hobbyist or a pro »), prototypage d'ingénierie et
robotique (« Engineering prototypes », « Robotics components »), et l'enseignement
(laboratoires universitaires, compétition nationale 3D). Une restriction brutale apparaît
en astérisque sous chaque bouton : **« \*Open to Non-individual Users Only »** — réservé
aux personnes morales. La page ne l'explique jamais.

**Le prix, affiché deux fois, en haut et en bas, à l'identique :**

- **`Super Early Bird $5,899`** — en vert, 41,6 px, gras
- **`(MSRP $8,399)`** — barré (`<s>`), gris `#C9C9C9`, 19,2 px

Soit une remise affichée de 30 %. La FAQ en bas de page ajoute un troisième palier,
jamais montré en haut : **un acompte de 50 $ remboursable débloque un « VIP price » de
5 699 $**, plus 200 $ de cashback et des cadeaux. Le mécanisme de prix complet n'est donc
lisible qu'après 29 000 px de défilement.

---

## 2. Structure, section par section

62 bandes au total. Hauteurs mesurées à 1440 px. Le rôle commercial est mon analyse ;
le contenu est ce qui est réellement dans la page.

| # | Position / hauteur | Section | Rôle commercial | Contenu réel |
|---|---|---|---|---|
| 1 | 0 → 65 px (65) | Bandeau d'annonce `#303030` | Rassurer / rattraper | Une ligne cliquable : « 🔉Important Update on the Xmachine WM-100 Project > » vers `xhorse3d.com/announcement` |
| 2 | 65 → 740 px (675) | **Hero** | Accrocher + vendre | Photo pleine largeur de la machine posée sur un établi, logo Xhorse3D, titre, sous-titre, prix, bouton, mention Kickstarter |
| 3 | 740 → 1506 px (766) | Mosaïque de 12 vignettes | Promettre (sommaire visuel) | Une image unique (`icon.png`, 1170 × 646) découpée visuellement en 12 cartes : Dual Cooling System, ±0.01mm, Optical Visual Positioning, 1500W/20,000rpm Spindle, Desktop Simultaneous 5-axis, XMakerHub AI & CAM, 6-Tool ATC, Wireless Probe, Multiple Material, Plasma Module |
| 4 | 1506 → 2687 px (1181) | **XMakerHub / FAO** | Lever l'objection n°1 (« je ne sais pas programmer ») | Titre vert, sous-titre, paragraphe, puis « Four Ways to Create » : 4 étapes numérotées 01-04 qui défilent toutes seules à côté d'une vidéo de l'interface |
| 5 | 2687 → 3458 px (771) | Chaîne automatisée | Prouver la simplicité | « Once you have your model… » + 5 puces + vidéo 8,8 s + note sur le G-code standard |
| 6 | 3458 → 4358 px (900) | **Bandeau vidéo plein écran** | Accrocher (émotion) | Vidéo 12,8 s d'un rouet de turbine usiné, texte blanc en surimpression |
| 7 | 4358 → 5173 px (815) | « Real Cuts. Real Parts. » | Prouver (preuve par la pièce) | Titre + **marquee infini de 60 photos** de pièces finies sur 3 rangées qui défilent en sens alternés |
| 8 | 5173 → 5770 px (597) | Communauté XMakerHub | Rassurer (écosystème) | Texte à gauche, vidéo à droite |
| 9 | 5770 → 6706 px (936) | « A New Age of Creation » | Vendre les usages | 3 onglets auto-rotatifs avec barre de progression : Engineering prototypes / Robotics components / Hobby workpieces, chacun une photo d'ambiance 1152 × 648 |
| 10 | 6706 → 8118 px (1412) | **« Makers need more than… »** | Lever l'objection « c'est un jouet » | Titre vert sur noir, puis deux cartes **en image** : « Real Simultaneous 5-Axis. Not 3+2. » et « Less Setup. Fewer Mistakes. Faster. », au-dessus d'une vidéo 6,9 s |
| 11 | 8118 → 10542 px (2424) | **Bloc specs narratives** | Prouver la performance | 4 sous-blocs alternés texte/visuel : 1500W, ±0.01mm, enveloppes de travail, chacun 450-468 px, séparés par des gouttières de 65 px |
| 12 | 10542 → 12935 px (2393) | Scan laser & caméra | Vendre la différenciation | Grand rendu en écorché du scanner laser bleu (1170 px), puis 3 blocs 457 px : positionnement laser, caméra temps réel, module plasma |
| 13 | 12935 → 13835 px (900) | « Works With Almost Everything » | Élargir le marché | Matériaux listés en texte sur fond vidéo |
| 14 | 13835 → 14918 px (1083) | Refroidissement + automatisation | Vendre le confort | « Dual Cooling System / Mist or Air » puis « Automatic. Effortless. » |
| 15 | 14918 → 16393 px (1475) | Changeur d'outils + « Load Once » | Vendre le gain de temps | Vidéo 1440 × 540, puis bande `#2B2B2B` avec 4 vignettes légendées Engraving / Milling / Drilling / Tapping / Threading |
| 16 | 16393 → 20091 px (3698) | **« An Intelligent CNC Experience »** | Prouver l'automatisation | 6 blocs de 450-540 px : palpeur sans fil, calibration d'axes, prise d'outil, étau auto-centrant, carter étanche, extraction des copeaux. Chaque bloc = une vidéo muette en boucle + 2 lignes de texte |
| 17 | 20091 → 21803 px (1712) | Châssis / encombrement | Rassurer (ça tient sur un bureau) | Grande image du bâti fonte d'aluminium + GIF |
| 18 | 21803 → 22379 px (576) | Bruit | Lever l'objection « trop bruyant » | Photo de la machine dans une cuisine lumineuse, encart chiffré dB, note de méthode |
| 19 | 22379 → 22841 px (462) | « See It in Action » | Prouver | Bande horizontale de **10 iframes YouTube** (450 × 244), dupliquées pour le défilement |
| 20 | 22841 → 24590 px (1749) | **« Specifications »** | Rassurer l'acheteur technique | **Une seule image PNG de 1170 × 1546** contenant tout le tableau |
| 21 | 24590 → 25808 px (1218) | « Worldwide Service Network » | Rassurer (SAV) | **Une image PNG de 1280 × 913** : 12 points SAV avec photo de façade, drapeau, raison sociale et adresse postale (UK, USA ×2, FRA, CAN, ZAF, ITA, MYS, THA, AUS, ESP, MEX) |
| 22 | 25808 → 27203 px (1395) | **Xhorse3D, la marque** | Rassurer (solidité de l'entreprise) | Texte + mosaïque usine/salons + 3 compteurs : 15 YEARS / 170+ Countries / 1 MILLION+ Global Users |
| 23 | 27203 → 27782 px (579) | Compétition nationale 3D | Prouver par le tiers | Texte + bande de 14 photos de la compétition |
| 24 | 27782 → 28335 px (553) | Boutiques physiques | Lever l'objection « produit fantôme » | Texte + 14 photos de magasins en Chine |
| 25 | 28335 → 28922 px (587) | **« A Proven Product »** | Lever l'objection crowdfunding | Texte + 20 photos d'atelier et de pièces |
| 26 | 28922 → 29372 px (450) | **CTA final** | Vendre | Répétition exacte du bloc prix + bouton du hero, sur photo d'atelier |
| 27 | 29372 → 29452 px (80) | « Social Medium » | — | 4 icônes : Facebook, groupe Facebook, Instagram, YouTube |
| 28 | 29452 → 30344 px (892) | **FAQs** | Lever les objections d'achat | 4 questions, en texte brut avec URLs collées en clair |

**Rythme vertical.** Les blocs tombent sur une grille implicite de **450 / 540 / 675 /
900 px**, séparés par des gouttières de **65 px**. Les bandes de titre font 130-330 px.
Il n'y a pas de respiration : 81 % de la hauteur de page contient au moins une image ou
une vidéo, et les sections s'enchaînent sans palier. Après 8 000 px, la page devient une
litanie de blocs de 450 px tous construits pareil (visuel d'un côté, 2 lignes de texte de
l'autre, alternance gauche/droite).

---

## 3. Le texte réel, verbatim

### Hero

> Bandeau : **`🔉Important Update on the Xmachine WM-100 Project >`**
>
> Sur-titre (image) : **`Xmachine WM-100`**
>
> Titre : **`Desktop 5-Axis CNC Machine`**
>
> Sous-titre : **`The world's first AI‑enabled desktop 5‑axis CNC series, the XM‑100 has already achieved over 1,000 deliveries, with tens of thousands of users having worked on it.`**
>
> Prix : **`Super Early Bird $5,899`** `(MSRP $8,399)`
>
> Bouton : **`Saving Big Now`**
>
> Sous le bouton (image) : **`LIVE NOW ON KICKSTARTER`**
>
> Mention : **`*Open to Non-individual Users Only | A Late But Kept Promise`**

Le libellé du bouton, `Saving Big Now`, est agrammatical. Il est répété tel quel aux deux
emplacements. C'est le **seul** bouton de toute la page.

### Intertitres, dans l'ordre

```
XMakerHub: AI-Powered 5-axis CAM Platform
    Zero CAM experience? No problem.
    Four Ways to Create
        01  Import an STL or STEP file   — use your existing CAD designs.
        02  Text to 3D                   — type a description, and AI generates a model.
        03  Image to 3D                  — upload a photo, and AI converts it into a 3D model.
        04  3D scan                      — capture real objects and turn them into digital models.
    Once you have your model, the rest is fully automated:
Meet Pro-Grade 5-Axis CNC-Right on Your Desk
Real Cuts. Real Parts. No Compromise
XMakerHub — Build. Share. Create.
A New Age of Creation
    Engineering prototypes / Robotics components / Hobby workpieces
Makers need more than just "a CNC machine."  →  You need:
    Real Simultaneous 5-Axis. Not 3+2.
    Less Setup. Fewer Mistakes. Faster.
5-Axis. Finally Desktop.  /  A New Age of Creation
    Advanced 1500W Power— Made In-House
    ±0.01mm *Positioning Repeatability  →  Precision—Every Time.
    One Machine, Multiple Envelopes – For Every Project
Non‑Contact Laser Scanning – Optical Visual Positioning Redefined
    Positioning Made Simple.  →  Blue Laser 3D Scanning to Position
    Know what's happening— at a glance.  →  Real-Time Machining Monitoring
    Plasma Module – No More Static Cling
Works With Almost Everything
Dual Cooling System  →  Mist or Air. You Choose.
Automatic. Effortless.  →  Less Setup. More Making.
    6-Tool Auto Tool Changer  →  Work Faster with Auto Tool Swap
Load Once. Make More.
An Intelligent CNC Experience
    Next-Gen Wireless Probe            (*Available as an optional accessory)
    Fully Automatic Axis Calibration
    Automatic Tool Setting
    Streamlines Workpiece Changes
    Full Enclosure – No Chip Escapes
    Enclosed Dust, Chip & Coolant Management
    Integrated Dust Extraction – Cleaner, Safer, Non‑Stop
Desktop Size. Pro-Grade Machining.  →  Fits Anywhere. Works Like a Beast.
Quiet, Focused, Desktop-Friendly  →  Noise Control That Lets You Work Anywhere.
See It in Action
Specifications
Worldwide Service Network
Xhorse3D — Explore the Boundary of Creation
Empowering the Next Generation of Engineers
Xmachine XM‑100 – Now Available in Offline Stores
A Proven Product – Not a Concept Machine
FAQs
```

### Les quatre phrases d'argumentaire qui portent la page

1. **`Xmachine WM-100 brings simultaneous 5-axis machining to your desktop—finally.`**
   *Le « finally » fait tout le travail : il postule que le lecteur attendait ça.*

2. **`With real 5-axis freedom, Pro-grade power, and a ridiculously smart workflow, it turns your desk into a production studio. From metal parts to complex prototypes, it machines what other "desktop" tools can only dream about. Faster runs, cleaner finishes, zero drama — just pure making power. Big-machine performance. Desktop freedom.`**
   *Registre « tech grand public » : adverbe familier (« ridiculously »), guillemets
   ironiques sur la concurrence (« desktop »), phrases nominales en rafale.*

3. **`XMakerHub is an AI-powered CAM platform that turns ideas into machinable parts—no manual programming required.`**
   *La promesse qui déplace le produit : on ne vend pas une machine, on vend la
   suppression de la FAO.*

4. **`Xmachine WM‑100 is not a prototype. Its predecessor, the XM‑100, has been shipping since 2025, with over 1,000 units delivered and tens of thousands of users across university labs, maker spaces, and production floors.`**
   *La seule phrase défensive de la page, et la plus efficace : elle répond à la peur
   réelle de l'acheteur Kickstarter.*

### Autres formules notables

- `WM-100 doesn't just move. It moves accurately.`
- `You load the material. WM-100 takes care of the rest. That's how desktop CNC should work.`
- `WM-100 isn't a "rotate-and-hope" machine.` *(dans une image)*
- `…eliminates manual repositioning and reduces setup time by 70%` *(dans une image)*
- `so you can focus on designing, not babysitting the machine.`
- `Small enough for a workshop or studio desk — powerful enough for aerospace-grade geometries.`
- `1 machine, 100+ possibilities.`
- `*Xmachine runs on standard G-code and works seamlessly with popular third-party CAM software – with dedicated post-processors provided.`

**Le registre, en une ligne :** anglais marketing américain de crowdfunding hardware,
phrases courtes et martelées, ponctuation en tirets cadratins, un superlatif par
paragraphe, et un vocabulaire d'atelier (chips, toolpath, touch-off, RTCP) assumé qui
suppose que le lecteur sait déjà ce qu'est une CNC. Aucune traduction : la page est en
anglais uniquement.

---

## 4. Direction artistique

**Fond : sombre, majoritairement.** `body` est en `#000000`, texte `#FFFFFF`. Environ
**58 % de la hauteur est noire, 42 % est claire** : les sections claires sont des îlots
insérés dans un fond noir, pas l'inverse. L'alternance est régulière jusqu'à 8 000 px,
puis la page bascule en noir quasi continu jusqu'au bout.

### Palette relevée (hexadécimal, lu dans `getComputedStyle`)

| Couleur | Usage |
|---|---|
| `#000000` | fond global, texte des boutons |
| `#FFFFFF` | texte courant sur fond sombre, bandes claires |
| **`#96C84B`** | **l'unique accent : vert pomme.** Prix, titres de section clés, fond du bouton, numéros d'étape, chiffres des compteurs |
| `#F5F5F5` / `#F7F7F7` / `#F2F2F2` / `#F0F0F0` | quatre gris clairs quasi identiques pour les bandes claires — incohérence de thème |
| `#303030` | bandeau d'annonce |
| `#2B2B2B` | bande « Load Once. Make More. » |
| `#C9C9C9` | prix MSRP barré |
| `#999999` / `#A4A4A4` / `#A5A5A5` | notes de bas de bloc, onglets inactifs |
| `#111111` | onglet actif sur fond clair |
| `#6B6B6B` | astérisques |

La page tient sur **deux couleurs** (noir/blanc) **plus un vert**. Aucun dégradé de
marque, aucune couleur secondaire. Tout ce qui est coloré sur les captures vient des
photos (bleu du laser, cyan des carters, orange du cuivre), pas de la charte.

### Typographie

**Une seule famille : Montserrat** (Google Fonts, graisses 400 / 500 / 700). Rien d'autre
sur toute la page, titres comme corps.

| Niveau | Taille | Graisse | Interligne | Couleur |
|---|---|---|---|---|
| Titre de section (`h1`) | **48 px** | 700 | 52,8 px (1,10) | `#FFFFFF` ou `#96C84B` |
| Titre hero | **38,4 px** | 700 | 54,9 px (1,43) | `#FFFFFF` |
| Très gros display (« 5-Axis. Finally Desktop. ») | **70 px** | 700 | 105 px (1,50) | `#F7F7F7` |
| Prix | **41,6 px** | 700 | 59,4 px | `#96C84B` |
| Sur-titre de bloc | 19,2 px / 17,6 px | 400-700 | 1,43 | `#FFFFFF` |
| Sous-titre de bloc (`h3`) | 21,6 px | 700 | 24,2 px (1,12), `-0.54px` | `#111111` / `#A5A5A5` |
| **Corps** | **16 px** | 400 | 22,86 px (**1,43**) | `#FFFFFF` ou `#000000` |
| Corps secondaire | 14,4 px | 400 | 20,6 px | — |
| Notes / astérisques | 14 px | 400 | 20 px | `#999999` |
| Bouton | 15 px | 700 | 30 px, `letter-spacing: 1px` | `#000000` |

Le contraste display/corps est de **48 / 16 = 3,0×**, ce qui est modeste pour une page de
ce type. L'interligne de corps à **1,43** est serré pour du 16 px.

### Largeur de colonne

Conteneur principal **1200 px**, blocs internes **1170 px**. Les paragraphes centrés des
bandes pleine largeur font **1150 à 1170 px de large** — soit **200 à 230 caractères par
ligne**. C'est deux à trois fois la longueur de ligne lisible. Dans les blocs à deux
colonnes, le texte retombe à **457-610 px** (70-90 caractères), ce qui est correct. La
page est donc typographiquement bonne dans ses blocs alternés et mauvaise dans toutes ses
sections centrées.

---

## 5. L'imagerie

**Inventaire sur la page desktop :**

| Type | Nombre affiché | Fichiers distincts | Surface |
|---|---|---|---|
| Images (`<img>`) | 92 | 59 | ≈ 15,7 Mpx |
| Vidéos (`<video>`) | 17 | 17 | ≈ 9,0 Mpx |
| YouTube (`<iframe>`) | 19 | 10 | ≈ 2,7 Mpx |

**Proportion : 81 % de la hauteur de page est occupée par des bandes contenant au moins un
média.** Seulement 5 855 px sur 30 344 sont du texte seul (titres et FAQ). C'est une page
d'images légendées, pas une page de texte illustrée.

**Nature des visuels :**

- **Photo produit en situation** (hero, section bruit, CTA final) : la machine **posée**,
  éclairée studio, sur un établi en bois ou un plan de cuisine, entourée de pièces
  usinées. Jamais en coupe sur ces plans-là.
- **Vidéos macro de coupe** (17, toutes de 3,6 à 12,8 s, `autoplay muted loop`, sans
  contrôles) : c'est le cœur du dispositif. La machine est montrée **en train de
  travailler**, en très gros plan, copeaux et liquide de coupe visibles. Durée moyenne
  7 s — la boucle est courte et hypnotique.
- **Rendus 3D en écorché** : un seul vrai, mais très grand (1170 px de large), pour le
  module de scan laser — carter rendu transparent, faisceau bleu visible. Un second
  rendu montre le bâti en fonte d'aluminium. Pas de vue éclatée au sens strict, pas de
  schéma coté.
- **Galeries de preuve** : ≈ 60 photos de pièces finies en marquee, 14 photos de
  compétition, 14 photos de magasins, 20 photos d'atelier, 12 photos de façades SAV.
  Toutes en vrac, non légendées (sauf le SAV), à des formats hétérogènes.
- **Lifestyle** : deux photos d'un homme travaillant à son bureau, une cuisine
  ensoleillée. C'est ce qui porte la promesse « desktop ».
- **Captures logicielles** : 3-4 vidéos de l'interface XMakerHub.
- **Aucun schéma technique, aucune cotation, aucun diagramme de cinématique 5 axes.**

**Le défaut majeur :** une part importante du texte est **gravée dans des images**. Les
deux cartes d'argumentaire « Real Simultaneous 5-Axis. Not 3+2. » et « Less Setup. Fewer
Mistakes. Faster. » (c'est là que vit la statistique « 70 % »), les légendes de la
mosaïque de 12 vignettes, les types de positionnement du palpeur, les mesures de bruit en
dB, le bandeau « LIVE NOW ON KICKSTARTER » — et surtout **le tableau de spécifications
entier et la carte du réseau SAV entière**, deux PNG de 1170 × 1546 et 1280 × 913. Ce
texte n'est ni sélectionnable, ni traduisible, ni lisible par un lecteur d'écran, ni
indexable, et il pixellise au zoom.

---

## 6. Comment les caractéristiques techniques sont présentées

**Trois registres successifs, du plus marketing au plus brut.**

1. **Gros chiffres isolés**, en vert, avec la méthode en astérisque minuscule juste après :
   `±0.01mm` suivi de `*Positioning Repeatability` en 14 px gris. `Advanced 1500W Power`.
   `20,000 rpm`. `6-Tool`. C'est la couche « accroche ».

2. **Blocs narratifs** : un titre, deux à quatre phrases, un visuel. Aucun chiffre n'y est
   justifié. C'est la couche « conviction ».

3. **Un tableau complet, tout à la fin, en image.** 18 lignes × 2 colonnes de paires
   libellé/valeur. Son contenu :

   | | | | |
   |---|---|---|---|
   | Numerical Control System | XMachine-NCS | Max. Workpiece Size | 5 axis : cyl. Φ140×120 mm / carré 110×110×120 mm — 3+2 axes : 150×150×120 mm — 3 axes : 150×200×120 mm |
   | Lathe Structure | Horizontal | X/Y/Z Positioning Accuracy | ±0.01 mm |
   | X/Y/Z Axis Travel | 156 / 200 / 125 mm | X/Y/Z Repeatability | ±0.01 mm |
   | A-axis Travel | −30° à 110° | A/C Positioning Accuracy | ±50″ |
   | C-axis Travel | 360° | A/C Repeatability | ±10″ |
   | Spindle Motor | High-precision Electric Spindle | X/Y/Z Rapid Traverse | 6000 mm/min |
   | Spindle Power | 1.5 kW | A-axis Max. Speed | 18 rpm |
   | Spindle Speed | 20 000 rpm | C-axis Max. Speed | 180 rpm |
   | Spindle Rated Torque | 0.6 N·m | Positioning Method | scan laser, palpeur sans fil, prise d'outil |
   | Spindle Max. Torque | 1.3 N·m | Machining Types | engraving, milling, drilling, tapping |
   | A-axis Rated Torque | 52 N·m | Supported Materials | titane, inox, alu, laiton, cuivre, bois, POM, ABS, jade, carbone, cire… |
   | A-axis Max. Torque | 191 N·m | Voltage | 100-240 V AC |
   | Collet | 60E | Rated Power | 2.2 kW |
   | Max. Tool Diameter | φ6 mm | Cooling System | Mist + Air |
   | ATC Capacity | 6 outils | Machine Dimensions | 797 × 614 × 580 mm |
   | ATC Type | Servo ATC | Package Dimensions | 995 × 790 × 795 mm |
   | Worktable Size | 150 mm | Net Weight | ≈ 130 kg |
   | Worktable Load | ≤ 12 kg | Gross Weight | ≈ 200 kg |

**Méthode de mesure : quasi absente.** Deux exceptions, et une seule est sérieuse.

- `±0.01mm` est qualifié de `*Positioning Repeatability` — mais rien sur la norme, la
  course testée, la température, le nombre de passes.
- Le **bruit** est le seul chiffre correctement encadré : valeurs séparées métal/plastique
  et ébauche/finition (≈ 70 dB intérieur / ≈ 50 dB extérieur en ébauche métal), avec la
  note **`Note: Outside measurements are taken with the door closed near the entrance. All values are based on lab-tested data.`**
  C'est le seul endroit de la page où l'on dit où est le micro.
- Le « 70 % de temps de réglage en moins » et le « ×2,5 de durée de vie outil » n'ont
  aucune base.

Pas d'onglets de comparaison, pas de pictogrammes normalisés, pas de fiche PDF
téléchargeable.

---

## 7. Les ressorts de vente

### Présents

| Ressort | Mise en œuvre |
|---|---|
| **Ancrage de prix** | `$5,899` vert contre `(MSRP $8,399)` barré gris. Remise de 30 % lisible d'un coup d'œil |
| **Palier d'early bird** | « Super Early Bird », plus un palier VIP à 5 699 $ caché en FAQ |
| **Acompte remboursable** | 50 $ → 200 $ de cashback + cadeaux, remboursé sous 14 jours après la fin de campagne |
| **Volumes vendus** | « over 1,000 deliveries », « tens of thousands of users », répété 3 fois |
| **Antériorité produit** | Section entière : « A Proven Product – Not a Concept Machine », prédécesseur XM-100 expédié depuis 2025 |
| **Solidité de l'entreprise** | 15 YEARS / 170+ Countries / 1 MILLION+ Global Users, 500+ ingénieurs, 600+ brevets, usine de 100 000 m² |
| **Caution institutionnelle** | « official CNC partner of the National 3D Competition » depuis deux ans, avec photos |
| **Preuve de distribution** | Magasins physiques en Chine, photos de clients en boutique |
| **SAV mondial** | 12 points de service nommés et **adressés**, avec photo de la façade |
| **Preuve par la pièce** | ≈ 60 photos de pièces réellement usinées |
| **Preuve vidéo** | 17 vidéos de coupe + 10 vidéos YouTube |
| **Urgence douce** | « LIVE NOW ON KICKSTARTER », « This offer will be close once our Kickstarter campaign goes live » |

### Absents

- **Aucun témoignage client.** Pas une citation, pas un nom, pas un visage attribué.
- **Aucun logo de presse**, aucune récompense, aucun prix de design.
- **Aucun comparatif** avec une machine concurrente — alors que l'argument central
  (« Not 3+2 », « what other "desktop" tools can only dream about ») appelle exactement ça.
- **Aucun compte à rebours.** Rien qui tourne, aucune date.
- **Aucune date de livraison.** La FAQ dit seulement « exact date coming soon ».
- **Aucune garantie annoncée** : pas de durée, pas de conditions, pas de retour.
- **Aucun compteur d'unités restantes.**
- **Aucun prix hors Kickstarter**, aucun devis, aucun contact commercial.
- **Aucun formulaire** : pas de capture d'e-mail, pas de newsletter, pas de rappel.
- **Aucune mention légale, aucun pied de page.**
- **Aucune explication** de la restriction « Non-individual Users Only », qui est pourtant
  disqualifiante pour une bonne partie du lectorat.

---

## 8. Éléments interactifs et animés

**Ce qui bouge tout seul :**

- **17 vidéos** `autoplay muted loop playsinline` sans contrôles, de 3,6 à 12,8 s. Elles
  démarrent toutes et tournent en permanence. C'est le principal poste de charge CPU.
- **4 marquees infinis** (`@keyframes scrollLeft` ×2, `scrollRight` ×1, `v1-scroll` ×1) :
  les galeries de pièces et de photos défilent horizontalement sans fin, à des sens
  alternés selon la rangée.
- **Un panneau à 4 étapes en CSS pur** (« Four Ways to Create ») : les keyframes
  `xhorseStepTitle1..4`, `xhorseStepDesc1..4` et `xhorseStepPanel1..4` font tourner le
  titre actif, sa description et le média associé. Des `<input type="radio">` masqués
  (1 × 1 px) permettent de cliquer pour forcer une étape.
- **Un carrousel à 3 onglets** (« A New Age of Creation ») : `bt3AutoSlide` + `bt3Title1..3`
  + une barre de progression verte qui se remplit sous l'onglet actif.
- **La bande YouTube** « See It in Action » défile horizontalement (les 10 vidéos sont
  dupliquées dans le DOM pour boucler sans couture).

**Ce qui réagit au survol :** 73 éléments portent `transition: all 0.3s` et 60 portent
`transition: transform 0.3s` — ce sont les vignettes de galerie et les cartes, qui se
zooment légèrement au survol. Le bouton vert, lui, n'a pas d'état de survol distinct.

**Ce qui suit le défilement : rien.** Aucun `position: sticky`, aucun `position: fixed`,
aucune apparition progressive, aucun parallaxe, aucun `IntersectionObserver`. Les
animations sont toutes en CSS et tournent qu'on les regarde ou non. Pas de barre d'achat
collante, pas d'en-tête réduit.

**Un bon point :** la feuille de style déclare `@media (prefers-reduced-motion: reduce)`,
donc les animations CSS sont neutralisées pour qui le demande. (Les vidéos en `autoplay`,
elles, ne le sont pas.)

**Responsive.** Les versions desktop et mobile sont **deux jeux de sections distincts dans
le même HTML**, montrés et masqués par les classes Bootstrap `hidden-xs`. 63 sections sur
115 sont marquées `hidden-xs`. Le mobile n'est donc pas une adaptation fluide : c'est une
seconde page, avec son propre recadrage du hero, sa mosaïque réorganisée en 2 colonnes et
des carrousels à flèches rondes vertes. Le coût est que **tout le contenu des deux
versions est téléchargé dans les deux cas**.

---

## 9. Ce qu'il faut en retenir pour une autre machine

### Ce qui marche, et pourquoi

**1. La vidéo macro en boucle est le meilleur argument de la page — et c'est transposable tel quel.**
Dix-sept clips de 3 à 12 secondes, muets, sans contrôles, montrant l'outil qui entre dans
la matière. Ça prouve en une seconde ce que trois paragraphes ne prouvent pas : la machine
coupe vraiment du métal. Pour une CNC, c'est le seul contenu qui lève le doute central de
l'acheteur. **À copier : filmer en très gros plan, boucle courte, pas de musique, pas de
voix off, et un clip par fonction plutôt qu'une vidéo de présentation unique.**

**2. La section « A Proven Product – Not a Concept Machine » répond à la vraie objection, nommément.**
Elle ne vend rien : elle désamorce la peur de l'acheteur de hardware (« est-ce que ce truc
existe ? »). Elle le fait avec trois éléments vérifiables : un prédécesseur daté, un volume
livré, des lieux d'usage. **À copier : identifier l'objection qui tue la vente, lui
consacrer une section à elle seule, et y répondre avec des faits datés plutôt qu'avec des
adjectifs.** Le réseau SAV avec adresses postales réelles relève de la même logique et vaut
plus que n'importe quel badge « garantie ».

**3. L'ancrage de prix est simple et il fonctionne.**
Un prix vert, un MSRP barré juste à côté, même ligne, même instant. Pas de tableau de
paliers, pas de calcul à faire. **À copier : le prix et sa référence barrée doivent être
visibles dans le premier écran, pas après un scroll.**

**4. La mosaïque de 12 vignettes juste sous le hero sert de sommaire visuel.**
Avant de dérouler 30 000 px, la page montre en un écran tout ce qu'elle va démontrer.
C'est ce qui donne au lecteur une raison de continuer. **À copier — mais en HTML, pas en
image.**

**5. Le même bloc prix+bouton, à l'identique, en haut et en bas.**
Deux occurrences, zéro variation, zéro bouton concurrent ailleurs. Toute la page pousse
vers une seule action. **À copier : un seul CTA, répété, jamais dilué.**

### Ce qu'il ne faut PAS copier

**1. Le texte gravé dans des images.**
Le tableau de specs entier en PNG de 1170 × 1546, la carte du SAV en PNG, les cartes
d'argumentaire, les chiffres de bruit. C'est invisible pour Google, illisible par un
lecteur d'écran, intraduisible, flou au zoom, et cassé sur un écran étroit. **Un tableau de
spécifications doit être un `<table>`.** C'est l'erreur la plus coûteuse de la page.

**2. Les 30 344 px.**
Après 8 000 px, la page devient une suite de 15 blocs de 450 px identiques dans leur
structure (vidéo d'un côté, titre + deux lignes de l'autre, alternance gauche/droite).
Il n'y a plus de hiérarchie : le changeur d'outils, l'étau et le port d'aspiration ont
exactement le même poids visuel que les 5 axes simultanés. **Hiérarchiser : trois
arguments en grand, le reste dans un tableau ou un accordéon.**

**3. Les lignes de 1150 px.**
200 à 230 caractères par ligne dans toutes les sections centrées. **Plafonner la colonne de
texte à 65-75 caractères**, soit ≈ 700 px en 16 px — ce que la page fait déjà très bien
dans ses blocs à deux colonnes, et oublie partout ailleurs.

**4. Les chiffres sans méthode.**
« ±0.01mm », « 70 % de réglage en moins », « ×2,5 de durée de vie outil » arrivent nus.
Sur une machine-outil, l'acheteur sérieux sait que « répétabilité » et « précision de
positionnement » ne sont pas la même chose, et qu'un chiffre sans protocole ne vaut rien.
La page le fait correctement **une seule fois**, pour le bruit, et c'est le passage le plus
crédible. **Généraliser cette note de méthode à tous les chiffres : c'est peu coûteux et
ça différencie immédiatement d'un argumentaire de crowdfunding.**

**5. L'absence de sortie pour celui qui n'achète pas aujourd'hui.**
Pas de formulaire, pas d'e-mail, pas de PDF, pas de contact, pas de date de livraison, pas
de garantie — et une restriction « Non-individual Users Only » jamais expliquée qui
disqualifie une partie des lecteurs sans leur proposer d'alternative. Un visiteur sur deux
arrive en bas sans rien pouvoir faire d'autre que partir. **Prévoir systématiquement une
seconde action à faible engagement** (fiche technique à télécharger, alerte de
disponibilité, demande de devis) à côté du bouton d'achat.
