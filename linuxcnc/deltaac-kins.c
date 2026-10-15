/********************************************************************
 * deltaac-kins.c — cinematique d'une DELTA LINEAIRE portant une TABLE A/C.
 *
 * Ce que ce module est
 * --------------------
 * La machine de ce projet a trois chariots verticaux relies par des paires de
 * bras en parallelogramme a une plateforme qui porte la broche, et SOUS cette
 * broche une table A/C — un berceau A portant un plateau C.
 *
 * LinuxCNC fournit les deux moities separement et aucune des deux seule :
 *
 *   - ``xyzac-trt-kins`` traite la table A/C, mais pose que les articulations
 *     0, 1 et 2 SONT X, Y et Z — c'est-a-dire un portique ;
 *   - ``lineardeltakins`` traite la delta, mais ignore A et C, et place ses
 *     colonnes a 90/210/330 degres SANS reglage possible.
 *
 * Ce module les compose. La composition est exacte et sans terme croise parce
 * que la plateforme de la delta TRANSLATE sans tourner :
 *
 *     piece (x,y,z,A,C) --[inverse TRT]--> machine (xm,ym,zm,A,C)
 *                       --[inverse delta]-> chariots (q0,q1,q2,A,C)
 *
 * Ce qui a ete verifie, et comment
 * ---------------------------------
 * L'etage TRT est une transcription LITTERALE de ``xyzacKinematicsForward`` et
 * ``xyzacKinematicsInverse`` (src/emc/kinematics/trtfuncs.c de LinuxCNC 2.9),
 * recopiee terme par terme pour qu'une relecture cote a cote soit possible.
 *
 * Sa fidelite n'est PAS supposee : ``tools/deltaac_bench.c`` compile les
 * fonctions de LinuxCNC depuis leur source et compare les nombres, sur des
 * poses qui font travailler A et C. Voir ``docs/adr/ADR-026``.
 *
 * ORIENTATION DES COLONNES — la broche qui n'existe nulle part ailleurs
 * ---------------------------------------------------------------------
 * ``lineardeltakins`` ecrit ses angles en dur. Un chassis dont la premiere
 * colonne n'est pas a 90 degres ne peut donc pas etre pilote par lui, et la
 * mesure a montre ce que cela coute : 22 mm d'ecart sur les cotes du kit,
 * sans qu'aucun controle ne s'en apercoive (ADR-025). Ce module publie donc
 * ``deltaac-kins.column-0-deg``.
 *
 * Ce que ce module ne fait pas
 * -----------------------------
 * Il ne connait ni la raideur de la delta, ni les singularites de bras, ni les
 * organes en collision. Il calcule une correspondance ; il ne juge pas si elle
 * est usinable — c'est le role du reste de la chaine, en amont.
 *
 * Compilation hors arbre LinuxCNC :
 *     halcompile --install deltaac-kins.c
 *
 * Licence : GPL v2, comme LinuxCNC dont les formules TRT sont reprises.
 ********************************************************************/

#include "kinematics.h"
#include "rtapi.h"
#include "rtapi_app.h"
#include "rtapi_math.h"
#include "hal.h"

/* ``TO_RAD`` vient de posemath.h, via kinematics.h — le meme que celui
 * qu'emploie trtfuncs.c. En redefinir un ici donnerait deux constantes pour
 * un seul radian, et le compilateur avait raison de le dire. */

/* Articulations : trois chariots, puis A, puis C. La numerotation suit celle
 * que ``xyzac-trt-kins`` annonce au chargement — Joint 3 ==> Axis A,
 * Joint 4 ==> Axis C — pour qu'une configuration ecrite pour l'un se relise
 * sans surprise pour l'autre. */
#define JQ0 0
#define JQ1 1
#define JQ2 2
#define JA  3
#define JC  4

struct haldata {
    /* Table A/C : les memes noms que xyzac-trt-kins, parce qu'un nom different
     * pour la meme grandeur est une occasion de se tromper au branchement.
     * ``x-offset`` n'est volontairement PAS publie : la cinematique xyzac ne
     * le lit pas, et publier une broche inerte ferait croire a un reglage. */
    hal_float_t *x_rot_point, *y_rot_point, *z_rot_point;
    hal_float_t *y_offset, *z_offset, *tool_offset;
    /* Delta : R est l'ECART des rayons (rotules de chariot moins rotules de
     * plateforme), L l'entraxe des bras, et l'angle de la premiere colonne. */
    hal_float_t *delta_r, *delta_l, *column_0_deg;
} *haldata;

static int comp_id;

/* Geometrie des colonnes, recalculee seulement quand elle change : ce sont
 * trois cosinus par periode de servo sinon, pour rien. */
static double g_r = -1.0, g_a0 = -1000.0;
static double cx[3], cy[3];

static void set_columns(double r, double a0)
{
    int i;
    if (r == g_r && a0 == g_a0) return;
    g_r = r; g_a0 = a0;
    for (i = 0; i < 3; i++) {
        double th = (a0 + 120.0 * i) * TO_RAD;
        cx[i] = r * cos(th);
        cy[i] = r * sin(th);
    }
}

/* ---------------------------------------------------- etage TRT (table A/C) */

/* Transcription de xyzacKinematicsInverse. Ordre des termes conserve. */
static void trt_inverse(double px, double py, double pz,
                        double a_deg, double c_deg,
                        double *xm, double *ym, double *zm)
{
    double x_rot_point = *(haldata->x_rot_point);
    double y_rot_point = *(haldata->y_rot_point);
    double z_rot_point = *(haldata->z_rot_point);
    double dy = *(haldata->y_offset);
    double dz = *(haldata->z_offset) + *(haldata->tool_offset);
    double a_rad = a_deg * TO_RAD;
    double c_rad = c_deg * TO_RAD;

    *xm = + cos(c_rad) * (px - x_rot_point)
          - sin(c_rad) * (py - y_rot_point)
          + x_rot_point;

    *ym = + sin(c_rad) * cos(a_rad) * (px - x_rot_point)
          + cos(c_rad) * cos(a_rad) * (py - y_rot_point)
          - sin(a_rad) * (pz - z_rot_point)
          - cos(a_rad) * dy
          + sin(a_rad) * dz
          + dy
          + y_rot_point;

    *zm = + sin(c_rad) * sin(a_rad) * (px - x_rot_point)
          + cos(c_rad) * sin(a_rad) * (py - y_rot_point)
          + cos(a_rad) * (pz - z_rot_point)
          - sin(a_rad) * dy
          - cos(a_rad) * dz
          + dz
          + z_rot_point;
}

/* Transcription de xyzacKinematicsForward. */
static void trt_forward(double xm, double ym, double zm,
                        double a_deg, double c_deg,
                        double *px, double *py, double *pz)
{
    double x_rot_point = *(haldata->x_rot_point);
    double y_rot_point = *(haldata->y_rot_point);
    double z_rot_point = *(haldata->z_rot_point);
    double dy = *(haldata->y_offset);
    double dz = *(haldata->z_offset) + *(haldata->tool_offset);
    double a_rad = a_deg * TO_RAD;
    double c_rad = c_deg * TO_RAD;

    *px = + cos(c_rad)              * (xm      - x_rot_point)
          + sin(c_rad) * cos(a_rad) * (ym - dy - y_rot_point)
          + sin(c_rad) * sin(a_rad) * (zm - dz - z_rot_point)
          + sin(c_rad) * dy
          + x_rot_point;

    *py = - sin(c_rad)              * (xm      - x_rot_point)
          + cos(c_rad) * cos(a_rad) * (ym - dy - y_rot_point)
          + cos(c_rad) * sin(a_rad) * (zm - dz - z_rot_point)
          + cos(c_rad) * dy
          + y_rot_point;

    *pz = + 0
          - sin(a_rad) * (ym - dy - y_rot_point)
          + cos(a_rad) * (zm - dz - z_rot_point)
          + dz
          + z_rot_point;
}

/* ------------------------------------------------------- etage delta */

/* Chariots depuis la plateforme. Le chariot est AU-DESSUS : les bras
 * descendent, donc le signe est +. L'autre racine decrirait un montage ou les
 * bras remontent, mecaniquement impossible sur ce chassis. */
static int delta_inverse(double x, double y, double z, double L, double *q)
{
    int i;
    double L2 = L * L;
    for (i = 0; i < 3; i++) {
        double dx = cx[i] - x, dy = cy[i] - y;
        double reste = L2 - dx * dx - dy * dy;
        if (reste < 0.0) return -1;      /* les bras ne joignent pas */
        q[i] = z + sqrt(reste);
    }
    return 0;
}

/* Plateforme depuis les chariots : intersection de trois spheres.
 *
 * On soustrait les equations deux a deux — les carres de x, y et z
 * disparaissent — ce qui donne (x, y) lineaires en z ; on reporte ensuite dans
 * une sphere, d'ou une equation du second degre en z. La racine retenue est la
 * plus BASSE, pour etre l'exact retour de ``delta_inverse``. */
static int delta_forward(const double *q, double L, double *x, double *y,
                         double *z)
{
    double k[3], A[2][2], e[2], f[2], det, inv[2][2], u[2], v[2];
    double ax, ay, aa, bb, cc, disc, r, z0, z1, zz;
    int j;

    for (j = 0; j < 3; j++) k[j] = cx[j] * cx[j] + cy[j] * cy[j] + q[j] * q[j];
    for (j = 0; j < 2; j++) {
        int i = j + 1;
        A[j][0] = -2.0 * (cx[i] - cx[0]);
        A[j][1] = -2.0 * (cy[i] - cy[0]);
        e[j] = k[0] - k[i];
        f[j] = 2.0 * (q[i] - q[0]);
    }
    det = A[0][0] * A[1][1] - A[0][1] * A[1][0];
    if (det == 0.0) return -1;           /* colonnes alignees : impossible */
    inv[0][0] =  A[1][1] / det; inv[0][1] = -A[0][1] / det;
    inv[1][0] = -A[1][0] / det; inv[1][1] =  A[0][0] / det;
    for (j = 0; j < 2; j++) {
        u[j] = inv[j][0] * e[0] + inv[j][1] * e[1];
        v[j] = inv[j][0] * f[0] + inv[j][1] * f[1];
    }

    ax = u[0] - cx[0];
    ay = u[1] - cy[0];
    aa = v[0] * v[0] + v[1] * v[1] + 1.0;
    bb = 2.0 * (ax * v[0] + ay * v[1] - q[0]);
    cc = ax * ax + ay * ay + q[0] * q[0] - L * L;
    disc = bb * bb - 4.0 * aa * cc;
    if (disc < 0.0) return -1;           /* aucun point reel */
    r = sqrt(disc);
    z0 = (-bb + r) / (2.0 * aa);
    z1 = (-bb - r) / (2.0 * aa);
    zz = (z0 < z1) ? z0 : z1;
    *z = zz;
    *x = u[0] + v[0] * zz;
    *y = u[1] + v[1] * zz;
    return 0;
}

/* -------------------------------------------------- interface LinuxCNC */

int kinematicsForward(const double *joints, EmcPose *pos,
                      const KINEMATICS_FORWARD_FLAGS *fflags,
                      KINEMATICS_INVERSE_FLAGS *iflags)
{
    double xm, ym, zm, px, py, pz;
    double q[3];
    (void)fflags; (void)iflags;

    set_columns(*(haldata->delta_r), *(haldata->column_0_deg));
    q[0] = joints[JQ0]; q[1] = joints[JQ1]; q[2] = joints[JQ2];
    if (delta_forward(q, *(haldata->delta_l), &xm, &ym, &zm)) return -1;
    trt_forward(xm, ym, zm, joints[JA], joints[JC], &px, &py, &pz);

    pos->tran.x = px; pos->tran.y = py; pos->tran.z = pz;
    pos->a = joints[JA];
    pos->c = joints[JC];
    pos->b = 0; pos->u = 0; pos->v = 0; pos->w = 0;
    return 0;
}

int kinematicsInverse(const EmcPose *pos, double *joints,
                      const KINEMATICS_INVERSE_FLAGS *iflags,
                      KINEMATICS_FORWARD_FLAGS *fflags)
{
    double xm, ym, zm, q[3];
    (void)iflags; (void)fflags;

    set_columns(*(haldata->delta_r), *(haldata->column_0_deg));
    trt_inverse(pos->tran.x, pos->tran.y, pos->tran.z, pos->a, pos->c,
                &xm, &ym, &zm);
    if (delta_inverse(xm, ym, zm, *(haldata->delta_l), q)) return -1;

    joints[JQ0] = q[0]; joints[JQ1] = q[1]; joints[JQ2] = q[2];
    joints[JA] = pos->a;
    joints[JC] = pos->c;
    return 0;
}

KINEMATICS_TYPE kinematicsType(void)
{
    return KINEMATICS_BOTH;
}

int rtapi_app_main(void)
{
    int r = 0;

    comp_id = hal_init("deltaac-kins");
    if (comp_id < 0) return comp_id;

    haldata = hal_malloc(sizeof(struct haldata));
    if (!haldata) { hal_exit(comp_id); return -1; }

    if (!r) r = hal_pin_float_newf(HAL_IN, &(haldata->x_rot_point), comp_id,
                                   "deltaac-kins.x-rot-point");
    if (!r) r = hal_pin_float_newf(HAL_IN, &(haldata->y_rot_point), comp_id,
                                   "deltaac-kins.y-rot-point");
    if (!r) r = hal_pin_float_newf(HAL_IN, &(haldata->z_rot_point), comp_id,
                                   "deltaac-kins.z-rot-point");
    if (!r) r = hal_pin_float_newf(HAL_IN, &(haldata->y_offset), comp_id,
                                   "deltaac-kins.y-offset");
    if (!r) r = hal_pin_float_newf(HAL_IN, &(haldata->z_offset), comp_id,
                                   "deltaac-kins.z-offset");
    if (!r) r = hal_pin_float_newf(HAL_IN, &(haldata->tool_offset), comp_id,
                                   "deltaac-kins.tool-offset");
    if (!r) r = hal_pin_float_newf(HAL_IN, &(haldata->delta_r), comp_id,
                                   "deltaac-kins.delta-r");
    if (!r) r = hal_pin_float_newf(HAL_IN, &(haldata->delta_l), comp_id,
                                   "deltaac-kins.delta-l");
    if (!r) r = hal_pin_float_newf(HAL_IN, &(haldata->column_0_deg), comp_id,
                                   "deltaac-kins.column-0-deg");
    if (r) { hal_exit(comp_id); return r; }

    /* AUCUNE cote par defaut plausible.
     *
     * ``lineardeltakins`` initialise R et L aux cotes « de quelqu'un » et le
     * dit. Ici, une delta mal dimensionnee demarre et usine faux : on laisse
     * donc des valeurs qui rendent la machine inutilisable tant que le HAL ne
     * les a pas posees — L = 0 fait echouer toute cinematique inverse, et cet
     * echec est bruyant et sans mouvement. */
    *(haldata->delta_r) = 0.0;
    *(haldata->delta_l) = 0.0;
    *(haldata->column_0_deg) = 0.0;

    rtapi_print("deltaac-kins : delta lineaire + table A/C. Articulations "
                "0,1,2 = CHARIOTS ; 3 = A ; 4 = C.\n");
    rtapi_print("deltaac-kins : delta-r, delta-l et column-0-deg DOIVENT etre "
                "posees par le HAL ; sans elles la cinematique echoue.\n");
    hal_ready(comp_id);
    return 0;
}

void rtapi_app_exit(void)
{
    hal_exit(comp_id);
}

#ifdef MODULE_INFO
MODULE_LICENSE("GPL");
#endif
