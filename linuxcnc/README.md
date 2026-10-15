# `deltaac-kins` — la cinématique de cette machine pour LinuxCNC

## Pourquoi ce module existe

LinuxCNC fournit les deux moitiés de cette machine, et aucune des deux seule :

| module | ce qu'il fait | pourquoi il ne suffit pas |
|---|---|---|
| `xyzac-trt-kins` | berceau A + plateau C | pose que les articulations 0, 1, 2 **sont** X, Y, Z — un portique |
| `lineardeltakins` | delta linéaire | ignore A et C, et écrit ses colonnes à 90/210/330° **sans réglage** |

Ce module les compose :

```
pièce (x,y,z,A,C) --[inverse TRT]--> machine (xm,ym,zm,A,C)
                  --[inverse delta]-> chariots (q0,q1,q2,A,C)
```

La composition est exacte et **sans terme croisé**, parce que la plateforme de
la delta translate sans tourner (paires de bras en parallélogramme).

## Articulations

| articulation | ce que c'est |
|---|---|
| 0, 1, 2 | les trois **chariots**, course identique (celle des colonnes) |
| 3 | A — le berceau |
| 4 | C — le plateau |

La numérotation suit celle que `xyzac-trt-kins` annonce au chargement
(*Joint 3 ==> Axis A, Joint 4 ==> Axis C*).

## Broches HAL

```
deltaac-kins.x-rot-point     deltaac-kins.delta-r         (écart des rayons)
deltaac-kins.y-rot-point     deltaac-kins.delta-l         (entraxe des bras)
deltaac-kins.z-rot-point     deltaac-kins.column-0-deg    (angle de la 1re colonne)
deltaac-kins.y-offset
deltaac-kins.z-offset
deltaac-kins.tool-offset
```

`x-offset` n'est **pas** publiée : la cinématique xyzac ne la lit pas, et une
broche inerte ferait croire à un réglage.

`column-0-deg` n'existe dans aucun module standard. C'est la raison d'être de
celui-ci : voir l'ADR-025, où 22 mm d'écart ont été mesurés.

**Aucune cote par défaut plausible.** `delta-r` et `delta-l` valent zéro au
chargement : une delta mal dimensionnée démarre et usine faux, alors que
`L = 0` fait échouer toute cinématique inverse — bruyamment, sans mouvement.

## Installer

```bash
halcompile --install deltaac-kins.c
halrun -f <(echo 'loadrt deltaac-kins'; echo 'show pin deltaac')
```

## Ce qui a été vérifié, et comment

`tools/verify_kinematics_linuxcnc.py --etage module --linuxcnc-source <arbre>`
compile ce module avec des bouchons HAL, et dans le **même binaire** la
cinématique delta de LinuxCNC, puis compare :

| | écart maximal |
|---|---|
| [A] contre la référence Python `delta_ac`, 80 poses | 5,7 × 10⁻¹⁴ mm |
| [B] son direct contre son propre inverse | 9,0 × 10⁻¹⁴ mm |
| [C] son étage delta contre celui de **LinuxCNC** (colonnes à 90°) | 2,8 × 10⁻¹⁴ mm |

[C] est le plus important : c'est le seul qui compare ce code à du code que
nous n'avons pas écrit.

## Chargé par LinuxCNC

LinuxCNC 2.9 compilé en `uspace`, module installé par `halcompile --install`,
puis `halrun -f <(echo 'loadrt deltaac-kins'; echo 'show pin deltaac')` : les
**neuf broches** ci-dessus sont listées, et les deux avertissements s'affichent.
Les noms sont donc lus, pas supposés.

Ce que cela n'établit pas : ce que LinuxCNC **calcule** quand il le fait
travailler. Il y faut la configuration complète, le démarrage, la prise
d'origine et des poses en MDI — l'étage 3 de l'outil de recoupement.

## Ce que cela n'établit pas

- **le signe des axes sur la machine réelle.** Aucun calcul ne l'établit : il
  faut commander un déplacement et regarder de quel côté la pièce part ;
- **où sont réellement les colonnes** (cote `delta_colonne_0_deg` de la fiche,
  non mesurée) ;
- la raideur de la delta et les singularités de bras ;
- les organes en collision — colonnes, anneau, bras balayés.

Ce module calcule une correspondance. Il ne juge pas si elle est usinable :
c'est le rôle du reste de la chaîne, en amont.
