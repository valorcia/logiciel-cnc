"""Le module de cinematique ECRIT PAR CE PROJET (jalon M26).

Ce que ces tests gardent, et ce qu'ils ne peuvent pas garder
============================================================

``linuxcnc/deltaac-kins.c`` compose la table A/C et la delta. Ces tests portent
sur sa SOURCE, parce qu'ils doivent tourner partout — y compris la ou LinuxCNC
n'est pas installe.

La verification NUMERIQUE, elle, demande un arbre source LinuxCNC et vit dans
``tools/verify_kinematics_linuxcnc.py --etage module`` : elle compile le module
et compare ses nombres a la reference Python, a son propre aller-retour, et a
la cinematique delta de LinuxCNC. Un test qui ne verifierait que du texte ne
remplace pas cette mesure — il garde ce que la mesure ne voit pas : les
promesses que la source fait a son lecteur.
"""

from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "linuxcnc" / "deltaac-kins.c"
BANC = Path(__file__).resolve().parents[1] / "tools" / "deltaac_bench.c"


@pytest.fixture(scope="module")
def source() -> str:
    return MODULE.read_text(encoding="utf-8")


def test_the_module_exists_and_is_a_kinematics_component(source):
    """Les trois fonctions que LinuxCNC appelle, et rien de moins.

    Un module qui n'exporterait que l'inverse se chargerait, et le direct
    silencieusement absent ferait echouer la prise d'origine d'une facon que
    personne ne rattacherait a la cinematique.
    """
    for f in ("kinematicsForward", "kinematicsInverse", "kinematicsType",
              "rtapi_app_main", "rtapi_app_exit"):
        assert f in source, f"{f} manquant"
    assert "KINEMATICS_BOTH" in source, (
        "la machine sait aller dans les deux sens : le declarer autrement "
        "priverait LinuxCNC du direct")


def test_the_column_orientation_is_a_hal_pin(source):
    """**La broche qui n'existe nulle part ailleurs.**

    `lineardeltakins` écrit ses angles en dur, et l'ADR-025 a mesuré ce que
    cela coûte : 22 mm d'écart sur les cotes du kit, sans qu'aucun contrôle ne
    s'en aperçoive. Un châssis dont la première colonne n'est pas à 90° ne peut
    donc pas être piloté par le module standard — c'est la raison d'être de
    celui-ci.
    """
    assert "deltaac-kins.column-0-deg" in source
    assert "deltaac-kins.delta-r" in source
    assert "deltaac-kins.delta-l" in source


def test_the_joint_numbering_matches_what_xyzac_trt_kins_announces(source):
    """Joint 3 ==> Axis A, Joint 4 ==> Axis C.

    Ce projet s'est deja trompe une fois sur ce point precis, en ecrivant C =
    articulation 5 avec un commentaire affirmant le contraire de ce que le
    module imprime au chargement.
    """
    assert "#define JA  3" in source
    assert "#define JC  4" in source
    for j in ("#define JQ0 0", "#define JQ1 1", "#define JQ2 2"):
        assert j in source, f"{j} : les trois premieres sont les CHARIOTS"


def test_no_plausible_default_dimensions(source):
    """Une delta mal dimensionnée démarre et usine faux.

    `lineardeltakins` initialise R et L aux cotes « de quelqu'un ». Ici les
    valeurs par défaut rendent la machine inutilisable tant que le HAL n'a rien
    posé : L = 0 fait échouer toute cinématique inverse, et cet échec est
    bruyant et sans mouvement — le bon mode d'échec.
    """
    assert "*(haldata->delta_l) = 0.0;" in source
    assert "*(haldata->delta_r) = 0.0;" in source
    assert "DOIVENT etre" in source, (
        "le module doit DIRE au chargement que ces cotes sont obligatoires")


def test_the_trt_stage_is_a_literal_transcription(source):
    """Les termes de `xyzacKinematicsInverse`, dans leur ordre.

    La fidélité n'est pas prouvée ici — elle l'est par l'étage `module` de
    l'outil de recoupement, qui compare les nombres à ceux de la fonction
    compilée de LinuxCNC. Ce test garde la forme : une « simplification » de la
    formule la ferait diverger en silence de la source qu'elle transcrit.
    """
    i = source.index("static void trt_inverse")
    corps = source[i:source.index("static void trt_forward")]
    for terme in ("cos(c_rad) * (px - x_rot_point)",
                  "sin(c_rad) * cos(a_rad) * (px - x_rot_point)",
                  "sin(c_rad) * sin(a_rad) * (px - x_rot_point)"):
        assert terme in corps, f"terme absent : {terme}"
    # dz absorbe tool_offset, comme dans la source
    assert "*(haldata->z_offset) + *(haldata->tool_offset)" in corps


def test_the_delta_stage_takes_the_root_where_the_arms_go_down(source):
    """Trois sphères se coupent en deux points, et l'autre décrirait un montage
    où les bras remontent vers la plateforme.

    Le même choix de signe que `DeltaLineaire.chariots` et que la référence
    Python — s'ils différaient, l'aller-retour du module ne se refermerait pas,
    et c'est précisément ce que mesure l'étage `module`.
    """
    i = source.index("static int delta_forward")
    corps = source[i:source.index("/* -------------------------------------------------- interface LinuxCNC")]
    assert "(z0 < z1) ? z0 : z1" in corps, "la racine la plus BASSE"
    inv = source[source.index("static int delta_inverse"):i]
    assert "z + sqrt(reste)" in inv, "le chariot est AU-DESSUS de la plateforme"
    assert "return -1" in inv, "les bras qui ne joignent pas sont un refus"


def test_the_bench_compiles_our_module_and_linuxcnc_in_one_binary():
    """Comparer deux calculs à travers un fichier intermédiaire ajoute une
    occasion de se tromper entre eux. Le banc les compile ensemble."""
    banc = BANC.read_text(encoding="utf-8")
    assert '#include "deltaac-kins.c"' in banc
    assert '#include "lineardeltakins-common.h"' in banc
    assert "--pins" in banc, (
        "les noms des broches se lisent du module, ils ne se supposent pas")


def test_the_module_states_what_it_does_not_do(source):
    """La règle du projet, appliquée à un fichier C comme au reste."""
    for mot in ("raideur", "singularites", "collision"):
        assert mot in source, f"« {mot} » : le module doit dire ce qu'il ignore"
