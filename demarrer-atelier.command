#!/bin/sh
# ATELIER XYZAC - double-cliquez (macOS) ou executez (Linux).
#
# Comme le .bat de Windows : ce fichier ne fait que passer la main a
# tools/demarrer_atelier.py, qui porte toute la logique et qui est le meme
# partout.
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" tools/demarrer_atelier.py "$@"
  fi
done
echo
echo "  Python n'est pas installe."
echo "  macOS    : telechargez-le sur https://www.python.org/downloads/"
echo "  Debian   : sudo apt install python3 python3-venv"
echo
exit 1
