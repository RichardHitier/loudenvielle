#!/usr/bin/env python3
"""Fabrique carte.html à partir du template et de randos-geo.json.

Les données sont injectées dans la page plutôt que chargées par fetch() :
un navigateur refuse de lire un JSON voisin quand la page est ouverte en
file://, et on veut pouvoir ouvrir carte.html d'un double-clic, sans
serveur.

Usage :
    python3 build_carte.py
    python3 build_carte.py randos-geo.json carte.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TEMPLATE = Path("carte.template.html")
MARQUEUR = "/*__DONNEES__*/[]"


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument(
        "entree", nargs="?", default="randos-geo.json", type=Path
    )
    parseur.add_argument("sortie", nargs="?", default="carte.html", type=Path)
    parseur.add_argument("--template", default=TEMPLATE, type=Path)
    args = parseur.parse_args()

    randos = json.loads(args.entree.read_text(encoding="utf-8"))
    placees = [r for r in randos if r.get("lat") and r.get("lon")]
    if not placees:
        print("aucune rando géocodée dans l'entrée", file=sys.stderr)
        return 1

    gabarit = args.template.read_text(encoding="utf-8")
    if MARQUEUR not in gabarit:
        print(f"marqueur {MARQUEUR} absent du template", file=sys.stderr)
        return 1

    # </script> dans une donnée fermerait la balise : on le neutralise.
    donnees = json.dumps(placees, ensure_ascii=False).replace("</", "<\\/")
    args.sortie.write_text(
        gabarit.replace(MARQUEUR, donnees), encoding="utf-8"
    )

    ignorees = len(randos) - len(placees)
    print(f"{len(placees)} randos → {args.sortie}", file=sys.stderr)
    if ignorees:
        print(f"  {ignorees} sans coordonnées, non affichées", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
