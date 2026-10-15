/* Banc d'epreuve de deltaac-kins.c.
 *
 * Il compile NOTRE module avec les bouchons HAL minimaux et appelle ses
 * fonctions. Dans le meme binaire, il compile aussi la cinematique DELTA de
 * LinuxCNC (lineardeltakins-common.h) afin que la comparaison ne passe par
 * aucun fichier intermediaire.
 *
 * Usage :
 *   deltaac_bench x_rp y_rp z_rp dy dz R L angle0
 * puis, une ligne par pose sur l'entree standard :
 *   i x y z a c    -> inverse  : rend "q0 q1 q2"
 *   f q0 q1 q2 a c -> direct   : rend "x y z"
 *   d x y z        -> delta de LINUXCNC seule (angles 90/210/330 en dur)
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <math.h>

#include "hal.h"
#include "kinematics.h"

/* --- bouchons HAL : les broches sont capturees par NOM a leur creation, ce
 *     qui permet de les poser depuis la ligne de commande. */
#define MAXPINS 32
static struct { char nom[128]; double *ptr; } pins[MAXPINS];
static int npins = 0;

void *hal_malloc(long int size) { return calloc(1, (size_t)size); }
int hal_init(const char *name) { (void)name; return 1; }
int hal_ready(int id) { (void)id; return 0; }
int hal_exit(int id) { (void)id; return 0; }
void rtapi_print(const char *fmt, ...) { (void)fmt; }
void rtapi_print_msg(msg_level_t level, const char *fmt, ...)
{ (void)level; (void)fmt; }

int hal_pin_float_newf(hal_pin_dir_t dir, hal_float_t **addr, int comp_id,
                       const char *fmt, ...)
{
    double *d = calloc(1, sizeof(double));
    va_list ap;
    (void)dir; (void)comp_id;
    *addr = (hal_float_t *)d;
    va_start(ap, fmt);
    vsnprintf(pins[npins].nom, sizeof(pins[npins].nom), fmt, ap);
    va_end(ap);
    pins[npins].ptr = d;
    npins++;
    return 0;
}

static int poser(const char *nom, double v)
{
    int i;
    for (i = 0; i < npins; i++)
        if (!strcmp(pins[i].nom, nom)) { *pins[i].ptr = v; return 0; }
    fprintf(stderr, "broche inconnue : %s\n", nom);
    return -1;
}

/* --- notre module, compile tel quel */
#include "deltaac-kins.c"

/* --- la delta de LinuxCNC, compilee telle quelle, pour comparaison */
#include "emcpos.h"
#include "lineardeltakins-common.h"

int main(int argc, char **argv)
{
    char ligne[512];

    if (argc >= 2 && !strcmp(argv[1], "--pins")) {
        int i;
        rtapi_app_main();
        for (i = 0; i < npins; i++) printf("%s\n", pins[i].nom);
        return 0;
    }
    if (argc < 9) {
        fprintf(stderr, "usage: deltaac_bench x_rp y_rp z_rp dy dz R L a0\n");
        return 2;
    }
    if (rtapi_app_main()) { fprintf(stderr, "init echouee\n"); return 1; }
    if (poser("deltaac-kins.x-rot-point", atof(argv[1]))
        || poser("deltaac-kins.y-rot-point", atof(argv[2]))
        || poser("deltaac-kins.z-rot-point", atof(argv[3]))
        || poser("deltaac-kins.y-offset",    atof(argv[4]))
        || poser("deltaac-kins.z-offset",    atof(argv[5]))
        || poser("deltaac-kins.delta-r",     atof(argv[6]))
        || poser("deltaac-kins.delta-l",     atof(argv[7]))
        || poser("deltaac-kins.column-0-deg", atof(argv[8]))) return 1;
    set_geometry(atof(argv[6]), atof(argv[7]));   /* la delta de LinuxCNC */

    while (fgets(ligne, sizeof(ligne), stdin)) {
        char quoi;
        double a, b, c, d, e;
        int n = sscanf(ligne, " %c %lf %lf %lf %lf %lf", &quoi, &a, &b, &c, &d, &e);
        if (n < 4) continue;
        if (quoi == 'i' && n == 6) {
            EmcPose p; double j[9];
            memset(&p, 0, sizeof(p)); memset(j, 0, sizeof(j));
            p.tran.x = a; p.tran.y = b; p.tran.z = c; p.a = d; p.c = e;
            if (kinematicsInverse(&p, j, NULL, NULL)) printf("nan nan nan\n");
            else printf("%.17g %.17g %.17g\n", j[0], j[1], j[2]);
        } else if (quoi == 'f' && n == 6) {
            EmcPose p; double j[9];
            memset(&p, 0, sizeof(p)); memset(j, 0, sizeof(j));
            j[0] = a; j[1] = b; j[2] = c; j[3] = d; j[4] = e;
            if (kinematicsForward(j, &p, NULL, NULL)) printf("nan nan nan\n");
            else printf("%.17g %.17g %.17g\n", p.tran.x, p.tran.y, p.tran.z);
        } else if (quoi == 'd') {
            EmcPose p; double j[9];
            memset(&p, 0, sizeof(p)); memset(j, 0, sizeof(j));
            p.tran.x = a; p.tran.y = b; p.tran.z = c;
            if (kinematics_inverse(&p, j)) printf("nan nan nan\n");
            else printf("%.17g %.17g %.17g\n", j[0], j[1], j[2]);
        }
        fflush(stdout);
    }
    return 0;
}
