"""Serveur de l'atelier. Bibliotheque STANDARD uniquement.

Pourquoi pas Flask ni FastAPI, alors que ce serait plus confortable a ecrire :
cet outil doit demarrer sur le Raspberry Pi d'un acheteur de kit, en une
commande, sans qu'il installe quoi que ce soit de plus. Une dependance de
serveur web se paie a chaque mise a jour et a chaque probleme de version, pour
un service que ``http.server`` rend ici tres bien — quelques routes JSON et des
images.

**Securite.** Ce serveur n'expose AUCUNE route qui atteigne une machine, et ce
module n'importe pas ``linuxcnc_gateway``. Un test le verifie sur l'AST. Il
n'ecoute que sur la boucle locale : ouvrir l'atelier sur le reseau
demanderait une decision que personne n'a prise.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .session import CORPUS, TAILLE_MAX, Session, rendu_3d

STATIQUE = Path(__file__).resolve().parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
         ".css": "text/css; charset=utf-8", ".png": "image/png"}


class Atelier(BaseHTTPRequestHandler):
    session: Session
    travail: Path

    # le journal par defaut ecrit une ligne par image : illisible
    def log_message(self, fmt, *args):            # noqa: A003
        pass

    def handle_one_request(self):
        """Un client qui s'en va n'est pas une erreur.

        La page remplace la source d'une image des qu'on clique une autre
        surface ; le navigateur annule alors la requete en cours, et
        ``http.server`` imprime dix lignes de ``BrokenPipeError`` dans le
        terminal. Rien n'est casse — mais quelqu'un qui monte un kit et qui
        lit une trace Python croit que si, et une trace qui apparait en
        fonctionnement normal apprend a ignorer les traces.
        """
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # ------------------------------------------------------------ utilitaires

    def _json(self, obj, code: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _fichier(self, chemin: Path, *, cache: bool = False) -> None:
        if not chemin.is_file():
            self._json({"erreur": "introuvable"}, 404)
            return
        data = chemin.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         TYPES.get(chemin.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control",
                         "max-age=60" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _corps(self) -> dict:
        n = int(self.headers.get("Content-Length", "0"))
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:                      # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        s = type(self).session

        if u.path in ("/", "/index.html"):
            return self._fichier(STATIQUE / "index.html")
        if u.path in ("/app.js", "/style.css"):
            return self._fichier(STATIQUE / u.path.lstrip("/"), cache=True)
        if u.path == "/api/etat":
            return self._json(s.etat())
        if u.path == "/api/exemples":
            return self._json({"exemples": Session.exemples()})
        if u.path == "/api/lancement":
            return self._json(s.lancement())
        if u.path == "/api/vue":
            if not s.piece_chargee:
                return self._json({"erreur": "aucune piece"}, 409)
            az = float(q.get("a", ["35"])[0])
            el = float(q.get("e", ["18"])[0])
            # La REVISION entre dans le nom : sans elle, la vue d'une piece
            # pouvait etre servie pour la suivante (voir Session.revision).
            out = type(self).travail / f"vue_{s.revision}_{az:.0f}_{el:.0f}.png"
            if not out.exists():
                try:
                    s.vue(out, azimut=az, elevation=el)
                except Exception as e:             # noqa: BLE001
                    # Sans ce filet, une panne de rendu remontait dans
                    # ``http.server``, qui coupe la connexion : le navigateur
                    # affichait une image vide et ne disait rien, la trace
                    # n'existant que dans le terminal. Une panne doit se dire
                    # la ou on la subit.
                    return self._json(
                        {"erreur": rendu_3d() or f"{type(e).__name__} : {e}"},
                        500)
            return self._fichier(out)
        if u.path == "/api/surface":
            i = int(q.get("i", ["0"])[0])
            if not s.piece_chargee or i >= len(s.surfaces):
                return self._json({"erreur": "surface inconnue"}, 404)
            az = float(q.get("a", ["35"])[0])
            el = float(q.get("e", ["18"])[0])
            out = (type(self).travail /
                   f"surf_{s.revision}_{i}_{az:.0f}_{el:.0f}.png")
            if not out.exists():
                try:
                    s.vue_surface(i, out, azimut=az, elevation=el)
                except Exception as e:             # noqa: BLE001
                    return self._json(
                        {"erreur": rendu_3d() or f"{type(e).__name__} : {e}"},
                        500)
            return self._fichier(out)
        if u.path == "/api/usinage":
            # « Comment cette face sera-t-elle usinee ? » — synchrone, comme le
            # diagnostic : 0,1 a 4 s mesurees, et l'operateur vient de cliquer.
            i = int(q.get("i", ["0"])[0])
            if not s.piece_chargee or i >= len(s.surfaces):
                return self._json({"erreur": "surface inconnue"}, 404)
            try:
                u2 = dict(s.usinage_surface(i))
            except Exception as e:                 # noqa: BLE001
                return self._json({"erreur": f"{type(e).__name__} : {e}"}, 500)
            # La trajectoire ne descend PAS au navigateur : cinq mille points
            # dont il ne ferait rien, et l'image les montre deja.
            u2.pop("tcp", None)
            return self._json(u2)

        if u.path == "/api/vue-usinage":
            i = int(q.get("i", ["0"])[0])
            if not s.piece_chargee or i >= len(s.surfaces):
                return self._json({"erreur": "surface inconnue"}, 404)
            f = max(0.0, min(1.0, float(q.get("f", ["0.5"])[0])))
            az = float(q.get("a", ["25"])[0])
            el = float(q.get("e", ["15"])[0])
            out = (type(self).travail /
                   f"usi_{s.revision}_{i}_{f:.2f}_{az:.0f}_{el:.0f}.png")
            if not out.exists():
                try:
                    s.vue_usinage(i, out, fraction=f, azimut=az, elevation=el)
                except ValueError as e:            # surface non usinable
                    return self._json({"erreur": str(e)}, 409)
                except Exception as e:             # noqa: BLE001
                    return self._json(
                        {"erreur": rendu_3d() or f"{type(e).__name__} : {e}"},
                        500)
            return self._fichier(out)

        if u.path == "/api/creux":
            # Les CREUX de la piece, et pour chacun : quel outil, depuis quelle
            # orientation, ou laquelle des trois etapes bloque. Synchrone comme
            # le reste de cette page : 3 a 10 s mesurees sur le corpus, et
            # l'operateur vient de cliquer sur l'onglet.
            if not s.piece_chargee:
                return self._json({"erreur": "aucune pièce"}, 404)
            try:
                return self._json({"creux": s.creux()})
            except Exception as e:                 # noqa: BLE001
                return self._json({"erreur": f"{type(e).__name__} : {e}"}, 500)

        if u.path == "/api/vue-creux":
            i = int(q.get("i", ["0"])[0])
            if not s.piece_chargee:
                return self._json({"erreur": "aucune pièce"}, 404)
            az = float(q.get("a", ["25"])[0])
            el = float(q.get("e", ["15"])[0])
            out = (type(self).travail /
                   f"creux_{s.revision}_{i}_{az:.0f}_{el:.0f}.png")
            if not out.exists():
                try:
                    s.vue_creux(i, out, azimut=az, elevation=el)
                except ValueError as e:            # creux non usinable
                    return self._json({"erreur": str(e)}, 409)
                except Exception as e:             # noqa: BLE001
                    return self._json(
                        {"erreur": rendu_3d() or f"{type(e).__name__} : {e}"},
                        500)
            return self._fichier(out)

        if u.path == "/api/image":
            i = int(q.get("i", ["0"])[0])
            return self._fichier(type(self).travail / "sim" / f"f{i:03d}.png")
        self._json({"erreur": "route inconnue"}, 404)

    # ----------------------------------------------------------------- POST

    def do_POST(self) -> None:                     # noqa: N802
        u = urlparse(self.path)
        s = type(self).session

        if u.path == "/api/televerser":
            return self._televerser(s)

        try:
            corps = self._corps()
        except (ValueError, json.JSONDecodeError):
            return self._json({"erreur": "corps illisible"}, 400)

        if u.path == "/api/piece":
            nom = str(corps.get("fichier", ""))
            # Pas de chemin arbitraire : seul un nom du corpus est accepte.
            # Un serveur local reste un serveur, et « local » n'est pas une
            # politique de securite.
            n = Path(nom).name
            chemin = CORPUS / n
            if not chemin.is_file():
                chemin = CORPUS.parent / "step_degraded" / n
            if not chemin.is_file():
                return self._json({"erreur": f"exemple inconnu : {nom}"}, 400)
            try:
                s.charger(chemin)
            except Exception as e:                 # noqa: BLE001
                # Le moteur peut refuser une geometrie pour une raison qu'il
                # sait expliquer. Rendre 500 perdrait l'explication.
                s.erreur = f"{type(e).__name__} : {e}"
            return self._json(s.etat())

        if u.path == "/api/reglages":
            for k, v in corps.items():
                if hasattr(s.reglages, k):
                    setattr(s.reglages, k, float(v))
            s.invalider()
            return self._json(s.etat())

        if u.path == "/api/coupe":
            # La matiere change le TEMPS, pas la faisabilite : elle n'invalide
            # donc PAS le verdict. Le relancer pour un changement d'alliage
            # ferait attendre quarante secondes pour rien.
            m = str(corps.get("matiere", "")).strip()
            if m not in s.coupe.matieres():
                return self._json({"erreur": f"matière inconnue : {m}"}, 400)
            s.coupe.matiere = m
            return self._json(s.etat())

        if u.path == "/api/bridage":
            # Le bridage, LUI, change la faisabilite : il invalide tout.
            forme = str(corps.get("forme", s.bridage.forme))
            if forme not in s.bridage.formes():
                return self._json({"erreur": f"montage inconnu : {forme}"}, 400)
            s.bridage.forme = forme
            if "axe_serrage" in corps:
                axe = str(corps["axe_serrage"])
                if axe not in ("x", "y"):
                    return self._json({"erreur": "axe de serrage : x ou y"}, 400)
                s.bridage.axe_serrage = axe
            for k in ("prise_mm", "n_brides", "recouvrement_mm",
                      "hauteur_brides_mm"):
                if k in corps:
                    setattr(s.bridage, k, float(corps[k]))
            s.invalider()
            return self._json(s.etat())

        if u.path == "/api/corriger":
            # Applique le decalage que le MOTEUR a calcule. Le corps est vide :
            # laisser l'IHM envoyer le vecteur aurait mis la valeur dans deux
            # endroits, dont un qui peut avoir change depuis l'affichage.
            if not s.appliquer_correction():
                return self._json({"erreur": "aucune correction proposée"}, 409)
            return self._json(s.etat())

        if u.path == "/api/diagnostic":
            i = int(corps.get("surface", 0))
            if not s.surfaces or i >= len(s.surfaces):
                return self._json({"erreur": "surface inconnue"}, 404)
            try:
                # Synchrone : une dichotomie coûte de 0,3 a 3 s mesurees, donc
                # moins qu'un rendu d'image, et l'operateur vient de cliquer.
                # Une tache de fond pour trois secondes ajouterait un etat a
                # suivre pour rien.
                s.diagnostiquer(i)
            except Exception as e:                 # noqa: BLE001
                s.erreur = f"{type(e).__name__} : {e}"
            return self._json(s.etat())

        if u.path == "/api/verifier":
            s.verifier()
            return self._json(s.etat())

        if u.path == "/api/simuler":
            dossier = type(self).travail / "sim"
            shutil.rmtree(dossier, ignore_errors=True)
            s.simuler(dossier, n=int(corps.get("images", 24)))
            return self._json(s.etat())

        self._json({"erreur": "route inconnue"}, 404)

    def _televerser(self, s: Session) -> None:
        """Recoit le fichier de l'operateur : corps BRUT, nom dans un en-tete.

        Pas de ``multipart/form-data``, alors que c'est la forme habituelle
        d'un envoi de fichier. Motif : l'analyser correctement demande soit une
        dependance, soit une centaine de lignes d'analyse de frontieres — pour
        transporter une seule chose, que le corps brut transporte tel quel. Le
        navigateur sait poster un ``File`` directement ; seul le NOM a besoin
        d'un canal, et un en-tete suffit.

        La taille est verifiee sur ``Content-Length`` AVANT lecture. Lire
        d'abord puis mesurer laisserait n'importe quel envoi remplir la memoire
        du Raspberry Pi — la borne ne servirait alors qu'apres le mal.
        """
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json({"erreur": "taille illisible"}, 400)
        if n > TAILLE_MAX:
            return self._json(
                {"erreur": f"fichier trop gros : {n / 1e6:.0f} Mo pour une "
                           f"limite de {TAILLE_MAX // 10**6} Mo"}, 413)
        nom = unquote(self.headers.get("X-Fichier", "") or "piece.step")
        donnees = self.rfile.read(n) if n else b""
        try:
            s.televerser(nom, donnees, type(self).travail / "televerse")
        except Exception as e:                     # noqa: BLE001
            s.erreur = f"{type(e).__name__} : {e}"
        return self._json(s.etat())


def servir(port: int = 8765, *, travail: Path | None = None,
           session: Session | None = None) -> ThreadingHTTPServer:
    """Cree le serveur, sans le lancer. Rendu tel quel pour les tests."""
    Atelier.session = session or Session()
    Atelier.travail = travail or Path(tempfile.mkdtemp(prefix="atelier-"))
    Atelier.travail.mkdir(parents=True, exist_ok=True)
    return ThreadingHTTPServer(("127.0.0.1", port), Atelier)
