"""python -m xyzac.ui.atelier — ouvre l'atelier dans le navigateur."""

import argparse
import threading
import webbrowser

from .server import servir


def main() -> int:
    ap = argparse.ArgumentParser(description="Atelier XYZAC (simulation seule)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--sans-navigateur", action="store_true")
    a = ap.parse_args()

    srv = servir(a.port)
    url = f"http://127.0.0.1:{a.port}/"
    print("=" * 62)
    print("  ATELIER XYZAC — SIMULATION UNIQUEMENT")
    print("  Aucune machine n'est pilotee par cette fenetre.")
    print("=" * 62)
    print(f"  Ouvrez : {url}")
    print("  Pour arreter : Ctrl+C")
    print("=" * 62)
    if not a.sans_navigateur:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\natelier ferme.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
