/* Banc d'appel direct de la cinematique DELTA de LinuxCNC, compilee depuis sa
 * source. Aucune transcription : ce sont les fonctions de
 * src/emc/kinematics/lineardeltakins-common.h.
 *
 * Usage :  delta_bench R L  puis, sur l'entree standard, une ligne par pose :
 *            i x y z        -> inverse : rend "q0 q1 q2"
 *            f q0 q1 q2     -> direct  : rend "x y z"
 *
 * Le format est volontairement pauvre : ce banc n'existe que pour etre compare
 * a un calcul Python, et tout ce qu'il ajouterait serait une occasion de plus
 * de se tromper entre les deux. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "emcpos.h"
#include "lineardeltakins-common.h"

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: delta_bench R L\n"); return 2; }
    set_geometry(atof(argv[1]), atof(argv[2]));

    char ligne[512];
    while (fgets(ligne, sizeof(ligne), stdin)) {
        char quoi;
        double a, b, c;
        if (sscanf(ligne, " %c %lf %lf %lf", &quoi, &a, &b, &c) != 4) continue;
        if (quoi == 'i') {
            EmcPose p; memset(&p, 0, sizeof(p));
            p.tran.x = a; p.tran.y = b; p.tran.z = c;
            double j[9]; memset(j, 0, sizeof(j));
            int r = kinematics_inverse(&p, j);
            if (r) printf("nan nan nan\n");
            else   printf("%.17g %.17g %.17g\n", j[0], j[1], j[2]);
        } else if (quoi == 'f') {
            double j[9]; memset(j, 0, sizeof(j));
            j[0] = a; j[1] = b; j[2] = c;
            EmcPose p; memset(&p, 0, sizeof(p));
            int r = kinematics_forward(j, &p);
            if (r) printf("nan nan nan\n");
            else   printf("%.17g %.17g %.17g\n", p.tran.x, p.tran.y, p.tran.z);
        }
        fflush(stdout);
    }
    return 0;
}
