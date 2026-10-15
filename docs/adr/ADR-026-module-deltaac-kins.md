# ADR-026 — `deltaac-kins` : le module de cinématique de cette machine

## Contexte

L'ADR-024 a refusé la configuration LinuxCNC parce qu'aucun module ne décrit
cette machine, et l'ADR-025 a mesuré pourquoi on ne pouvait pas reprendre celui
de LinuxCNC tel quel. Ce module est la suite.

| module de LinuxCNC | ce qu'il fait | pourquoi il ne suffit pas |
|---|---|---|
| `xyzac-trt-kins` | berceau A + plateau C | pose que les articulations 0, 1, 2 **sont** X, Y, Z |
| `lineardeltakins` | delta linéaire | ignore A et C, colonnes à 90/210/330° **en dur** |

## Décision

`linuxcnc/deltaac-kins.c`, composant halcompile autonome — il ne demande pas de
recompiler LinuxCNC.

### Trois choses qu'il fait et que le module standard ne fait pas

**1. Il compose les deux étages.** Sans terme croisé, parce que la plateforme
de la delta translate sans tourner. C'est ce qui rend le module court, et c'est
vérifié plutôt que supposé.

**2. Il publie `column-0-deg`.** `lineardeltakins` écrit ses angles en dur ;
l'ADR-025 a mesuré ce que cela coûte — **22 mm** sur les cotes du kit, sans
qu'aucun contrôle ne s'en aperçoive. Un châssis dont la première colonne n'est
pas à 90° ne peut pas être piloté par le module standard.

**3. Il n'a aucune cote par défaut plausible.** `lineardeltakins` initialise R
et L aux cotes « de quelqu'un » et le dit. Ici elles valent **zéro** : une
delta mal dimensionnée démarre et usine faux, alors que `L = 0` fait échouer
toute cinématique inverse — bruyamment, et sans mouvement. C'est le bon mode
d'échec, et il est choisi.

Il ne publie pas `x-offset` : la cinématique xyzac ne la lit pas, et une broche
inerte ferait croire à un réglage.

## Ce qui a été vérifié, et comment

`tools/deltaac_bench.c` compile **notre module et celui de LinuxCNC dans le
même binaire** — comparer deux calculs à travers un fichier intermédiaire
ajouterait une occasion de se tromper entre eux. L'étage est reproductible :
`verify_kinematics_linuxcnc.py --etage module`.

| | écart maximal |
|---|---|
| [A] contre la référence Python `delta_ac`, 80 poses tirées au hasard | **5,7 × 10⁻¹⁴ mm** |
| [B] son direct contre son propre inverse | **9,0 × 10⁻¹⁴ mm** |
| [C] son étage delta contre celui de **LinuxCNC** (colonnes à 90°, A = C = 0) | **2,8 × 10⁻¹⁴ mm** |

**[C] est le seul qui compare ce code à du code que nous n'avons pas écrit**,
et c'est pour cela qu'il existe. [A] et [B] seuls seraient un miroir : une
erreur commune aux deux implémentations les rendrait parfaitement d'accord et
toutes deux fausses.

L'étage TRT du module est une transcription littérale de `trtfuncs.c`, dont la
fidélité est elle-même mesurée par l'étage `source` — 7,1 × 10⁻¹⁵ mm sur
56 poses contre la fonction compilée de LinuxCNC.

## Ce que cela n'établit PAS

### Il a été chargé par LinuxCNC

C'est l'épreuve que ce projet s'impose depuis qu'elle a relevé cinq défauts sur
la configuration du jalon M9. LinuxCNC 2.9 a été compilé ici en mode `uspace`,
le module installé par `halcompile --install`, et chargé :

```
$ halrun -f <(echo 'loadrt deltaac-kins'; echo 'show pin deltaac')
deltaac-kins : delta lineaire + table A/C. Articulations 0,1,2 = CHARIOTS ; 3 = A ; 4 = C.
deltaac-kins : delta-r, delta-l et column-0-deg DOIVENT etre posees par le HAL ; sans elles la cinematique echoue.

Component Pins:
Owner   Type  Dir         Value  Name
     4  float IN              0  deltaac-kins.column-0-deg
     4  float IN              0  deltaac-kins.delta-l
     4  float IN              0  deltaac-kins.delta-r
     4  float IN              0  deltaac-kins.tool-offset
     4  float IN              0  deltaac-kins.x-rot-point
     4  float IN              0  deltaac-kins.y-offset
     4  float IN              0  deltaac-kins.y-rot-point
     4  float IN              0  deltaac-kins.z-offset
     4  float IN              0  deltaac-kins.z-rot-point
```

Les neuf broches annoncées, et les deux avertissements. Les noms sont donc
**lus**, pas supposés — c'est précisément sur une correspondance de noms que ce
projet s'était trompé au jalon M9.

### Ce qu'il n'a PAS encore subi

**Une trajectoire.** Le charger établit que le composant est bien formé et que
ses broches portent les noms annoncés. Cela ne dit rien de ce que LinuxCNC
calcule quand il le fait travailler : il faut la configuration complète —
blocs `[JOINT_n]` aux courses de chariot, prise d'origine, câblage HAL des
trois broches delta — puis démarrer, prendre l'origine, commander des poses en
MDI et relire les articulations. C'est l'étage 3 de
`verify_kinematics_linuxcnc.py`, et c'est le chantier suivant.

Et par ailleurs :


- le **signe** des axes sur la machine réelle. Aucun calcul ne l'établit : il
  faut commander un déplacement et **regarder** de quel côté la pièce part ;
- **où sont réellement les colonnes** — cote `delta_colonne_0_deg`, à `PLAN` ;
- la **raideur** de la delta et les singularités de bras ;
- les **organes en collision** : colonnes, anneau, bras balayés.

## Ce que la configuration fait en attendant

`build_config` **refuse toujours**. Le refus ne dit plus « le module n'existe
pas » : il dit où il est, ce qui a été vérifié, et ce qui ne l'a pas été.

Le précédent est net et il est dans ce dépôt : le jalon M9 avait livré une
configuration que LinuxCNC n'avait jamais lue, sur la conviction qu'il n'était
pas installable. Il l'était, et la configuration portait **cinq défauts, dont
deux silencieux**. Générer avant de charger serait refaire exactement cela.
