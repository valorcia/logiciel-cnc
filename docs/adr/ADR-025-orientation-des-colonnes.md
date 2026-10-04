# ADR-025 — Où sont les colonnes : vingt millimètres d'écart, et rien qui le dise

## Contexte

L'ADR-024 a établi la composition delta ∘ table A/C et refusé la configuration
LinuxCNC tant que le module C n'existe pas. Avant d'écrire ce module, une
question se posait : LinuxCNC fournit déjà `lineardeltakins` — ses formules
peuvent-elles être reprises telles quelles ?

La réponse a été mesurée, pas supposée. `tools/delta_bench.c` compile la
cinématique delta de LinuxCNC depuis sa source et l'appelle.

## Ce que la mesure a donné

Sur les cotes du kit — R = 110 mm, L = 250 mm :

| | écart maximal sur 8 points |
|---|---|
| modèle tel quel | **22,1 mm** |
| modèle avec les colonnes à 90 / 210 / 330° | **2,8 × 10⁻¹⁴ mm** |

Une seule cause, et elle tient en une ligne de l'en-tête de LinuxCNC :

> *Tower 0 is at (0,R). (note: this is not at zero radians!)*

`lineardeltakins` place ses colonnes à **90, 210 et 330°**. Ce projet les
plaçait à **0, 120 et 240°**, avec ce commentaire : *« la disposition d'une
delta à trois colonnes, et celle qu'on voit sur le châssis »*.

**Aucun des deux calculs n'est faux.** Chacun est juste pour *sa* disposition.
Ce qui était faux, c'est que la question n'était posée nulle part.

## Pourquoi c'est grave, et pourquoi ça ne se voit pas

Une erreur de 90° sur l'orientation des colonnes :

- **ne fait échouer aucun démarrage** — les formules restent valides ;
- **ne déplace pas la pièce d'un cheveu au centre du plateau** : les trois
  colonnes y sont équidistantes, donc les deux conventions y répondent la même
  chose. Un essai au centre ne révèle **rien**, et c'est le premier essai que
  n'importe qui ferait ;
- **change les positions de chariot de deux centimètres** dès qu'on s'éloigne,
  sur une machine dont la tolérance visée est de 0,02 mm.

C'est exactement le mode d'échec que ce projet passe son temps à traquer : une
grandeur juste pour une question, lue comme si elle répondait à une autre.

## Décision

### 1. L'orientation devient une cote de la fiche

`delta_colonne_0_deg`, 52ᵉ cote, **non mesurée** comme les 51 autres. Elle se
**regarde**, elle ne se calcule pas : debout devant la machine, repérer la
colonne la plus proche de X+ (vers la droite) — son angle vaut 0 ; si une
colonne est au contraire vers l'arrière (Y+), il vaut 90.

Son aide dit ce qu'elle coûte : *« une erreur de 90° fait calculer des
positions de chariot fausses de 20 mm sans qu'aucun contrôle ne s'en
aperçoive »*.

### 2. Le désaccord est constaté, pas arbitré

`accord_avec_lineardeltakins` répond à une question précise : **le module
standard de LinuxCNC peut-il décrire ce châssis ?** Il ne tranche pas la
question physique — il ne le peut pas — il dit qu'elle est ouverte.

Le refus de `build_config` porte désormais **deux** obstacles au lieu d'un, et
le second est le plus silencieux des deux.

### 3. Le module C devra exposer l'orientation en broche HAL

`lineardeltakins` l'écrit en dur et n'offre que `R` et `L`. Un châssis dont les
colonnes ne sont pas à 90/210/330 **ne peut pas** être piloté par le module
standard. Le module à écrire la prendra donc en paramètre — c'est une
conséquence de cette mesure, et elle change ce qu'il faut écrire.

### 4. Un quatrième étage de vérification

`verify_kinematics_linuxcnc.py --etage delta` compile et appelle la cinématique
delta de LinuxCNC, comme l'étage 2 le fait pour la table. Les étages 1 à 3 ne
portaient que sur la **moitié haute** de la machine ; la moitié basse n'avait
aucun recoupement, et c'est là que se cachait l'écart le plus coûteux.

Ses points d'épreuve incluent délibérément le **centre**, qui ne révèle rien :
le garder documente le piège au lieu de l'éviter.

## Ce que cela n'établit pas

- **Où sont réellement les colonnes.** C'est une question physique, et la cote
  est à `PLAN` tant que personne n'a regardé la machine ;
- le module C n'existe toujours pas ;
- rien n'est généré, et `linuxcnc_gateway` reste verrouillé.
