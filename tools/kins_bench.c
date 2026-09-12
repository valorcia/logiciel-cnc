/* Banc d'appel direct de xyzacKinematicsInverse, compile depuis la source
 * de LinuxCNC. Aucune transcription : c'est la fonction de LinuxCNC.
 *
 * Bouchons pour les quatre seuls symboles externes dont trtfuncs.c a besoin.
 * Les broches HAL sont capturees par NOM au moment de leur creation, ce qui
 * permet de leur donner une valeur depuis la ligne de commande. */
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include "hal.h"
#include "motion.h"
#include "switchkins.h"

#define MAXPINS 32
static struct { char nom[128]; double *ptr; } pins[MAXPINS];
static int npins = 0;

void *hal_malloc(long int size) { return calloc(1, (size_t)size); }

int hal_pin_float_newf(hal_pin_dir_t dir, hal_float_t **addr, int comp_id,
                       const char *fmt, ...)
{
    (void)dir; (void)comp_id;
    double *d = calloc(1, sizeof(double));
    *addr = (hal_float_t *)d;
    va_list ap; va_start(ap, fmt);
    vsnprintf(pins[npins].nom, sizeof(pins[npins].nom), fmt, ap);
    va_end(ap);
    pins[npins].ptr = d;
    npins++;
    return 0;
}

void rtapi_print(const char *fmt, ...) { (void)fmt; }
KINEMATICS_TYPE kinematicsType(void) { return KINEMATICS_BOTH; }
void rtapi_print_msg(msg_level_t level, const char *fmt, ...) { (void)level; (void)fmt; }

static int poser(const char *nom, double v)
{
    for (int i = 0; i < npins; i++)
        if (strstr(pins[i].nom, nom)) { *pins[i].ptr = v; return 1; }
    return 0;
}

int main(int argc, char **argv)
{
    kparms kp;
    memset(&kp, 0, sizeof(kp));
    kp.kinsname = "xyzac-trt-kins";
    kp.halprefix = "xyzac-trt-kins";
    kp.required_coordinates = "xyzac";
    kp.allow_duplicates = 1;
    kp.max_joints = EMCMOT_MAX_JOINTS;
    kp.sparm = NULL;

    if (trtKinematicsSetup(1, "xyzac", &kp)) {
        fprintf(stderr, "setup a echoue\n");
        return 2;
    }
    if (argc == 2 && !strcmp(argv[1], "--pins")) {
        for (int i = 0; i < npins; i++) printf("%s\n", pins[i].nom);
        return 0;
    }
    /* argv : x_rp y_rp z_rp dy dz  puis des quintuplets x y z a c sur stdin */
    if (argc != 6) {
        fprintf(stderr, "usage: %s x_rp y_rp z_rp dy dz  < poses\n", argv[0]);
        return 2;
    }
    if (!poser("x-rot-point", atof(argv[1])) ||
        !poser("y-rot-point", atof(argv[2])) ||
        !poser("z-rot-point", atof(argv[3])) ||
        !poser("y-offset",    atof(argv[4])) ||
        !poser("z-offset",    atof(argv[5]))) {
        fprintf(stderr, "une broche attendue est absente\n");
        return 2;
    }
    poser("tool-offset", 0.0);
    poser("x-offset", 0.0);

    double x, y, z, a, c;
    while (scanf("%lf %lf %lf %lf %lf", &x, &y, &z, &a, &c) == 5) {
        EmcPose pos; memset(&pos, 0, sizeof(pos));
        pos.tran.x = x; pos.tran.y = y; pos.tran.z = z;
        pos.a = a; pos.c = c;
        double joints[EMCMOT_MAX_JOINTS];
        memset(joints, 0, sizeof(joints));
        if (xyzacKinematicsInverse(&pos, joints, NULL, NULL)) {
            printf("ERREUR\n");
            continue;
        }
        printf("%.17g %.17g %.17g\n", joints[0], joints[1], joints[2]);
    }
    return 0;
}
