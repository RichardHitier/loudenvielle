#!/usr/bin/env python3
"""Génère les cinq feuilles PDF à partir de carte.html.

Quatre cartes en paysage, une par niveau, avec les points colorés et
numérotés, sans la liste ; puis une feuille portrait listant les randos
(numéro, titre, temps total, page).

La page se met elle-même en configuration d'export via l'URL et signale
qu'elle est prête ; ici on ne fait que lancer un Chrome sans interface et
lui demander d'imprimer.

Usage :
    python3 build_pdfs.py
    python3 build_pdfs.py --sortie pdf --page carte.html
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote

NIVEAUX = ["Promeneur", "Marcheur", "Randonneur", "Expérimenté"]

# Chrome imprime à la fin de ce budget de temps virtuel. Il faut de quoi
# charger toutes les tuiles du cadrage : mesuré autour de 10 s, on double.
BUDGET_MS = 30000

NAVIGATEURS = ["google-chrome", "chromium", "chromium-browser"]


def trouver_navigateur() -> str | None:
    for nom in NAVIGATEURS:
        chemin = shutil.which(nom)
        if chemin:
            return chemin
    return None


def sans_accent(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def imprimer(navigateur: str, url: str, cible: Path) -> bool:
    commande = [
        navigateur,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--virtual-time-budget={BUDGET_MS}",
        f"--print-to-pdf={cible}",
        url,
    ]
    resultat = subprocess.run(commande, capture_output=True, text=True)
    if not cible.exists() or cible.stat().st_size == 0:
        print(f"  échec : {resultat.stderr.strip()[:200]}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--page", default=Path("carte.html"), type=Path)
    parseur.add_argument("--sortie", default=Path("pdf"), type=Path)
    args = parseur.parse_args()

    navigateur = trouver_navigateur()
    if not navigateur:
        print(
            "aucun Chrome/Chromium trouvé : " + ", ".join(NAVIGATEURS),
            file=sys.stderr,
        )
        return 1

    page = args.page.resolve()
    if not page.exists():
        print(
            f"{page} absent — lancer d'abord build_carte.py", file=sys.stderr
        )
        return 1

    args.sortie.mkdir(exist_ok=True)

    feuilles = [
        (
            f"randos-{sans_accent(niveau).lower()}.pdf",
            f"feuille=carte&niveau={quote(niveau)}",
            f"carte {niveau}",
        )
        for niveau in NIVEAUX
    ]
    feuilles.append(("randos-liste.pdf", "feuille=liste", "liste des randos"))

    echecs = 0
    for nom, requete, libelle in feuilles:
        cible = args.sortie / nom
        print(f"{libelle} → {cible}", file=sys.stderr)
        if not imprimer(navigateur, f"file://{page}?{requete}", cible):
            echecs += 1

    total = len(feuilles)
    print(f"\n{total - echecs}/{total} feuilles générées", file=sys.stderr)
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
