#!/usr/bin/env python3
"""Géocode les randonnées de randos.json et écrit randos-geo.json.

Chaque rando est cherchée par son titre, d'abord dans l'API Géoplateforme
de l'IGN (toponymes officiels : cols, pics, lacs, refuges), puis dans
Nominatim/OSM en secours. Les résultats hors de la zone du massif (BBOX)
sont rejetés, et parmi les candidats restants on garde celui dont le nom
ressemble le plus au titre.

Champs ajoutés à chaque rando :
    lat, lon          coordonnées WGS84, ou null si rien de fiable
    geo_source        "ign", "osm" ou null
    geo_nom           nom renvoyé par l'API (à comparer au titre)
    geo_commune       commune du résultat, quand l'API la donne
    geo_similarite    0..1, ressemblance titre / nom renvoyé
    geo_score         score brut de l'API (non comparable entre sources)

Usage :
    python3 geocode_randos.py            # randos.json -> randos-geo.json
    python3 geocode_randos.py in.json out.json
    python3 geocode_randos.py --no-cache
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Zone d'intérêt : Cauterets / Luz-Saint-Sauveur / Barèges / Néouvielle /
# vallée d'Aure / Loudenvielle. Tout résultat hors de cette boîte est écarté,
# c'est ce qui évite qu'un « Col de Bastan » homonyme parte à l'autre bout
# du pays.
BBOX = (-0.30, 42.60, 0.60, 43.10)  # lon_min, lat_min, lon_max, lat_max
CENTRE_LON, CENTRE_LAT = 0.15, 42.85

IGN_URL = "https://data.geopf.fr/geocodage/search"
OSM_URL = "https://nominatim.openstreetmap.org/search"

# Nominatim exige un User-Agent identifiant. Pour un usage plus intensif,
# y mettre une adresse de contact.
USER_AGENT = "randos-geo/1.0 (script perso de geocodage de randonnees)"

IGN_DELAY = 0.2
OSM_DELAY = 1.0  # politique d'usage Nominatim : 1 requête/seconde maximum

# Seuil de ressemblance en dessous duquel on préfère ne rien affirmer.
SEUIL_SIMILARITE = 0.45

CACHE_PATH = Path(".geocache.json")

# Corrections manuelles appliquées après coup (voir --overrides).
OVERRIDES_PATH = Path("overrides.json")

# Au-delà de cette distance de la médiane du massif, un point est signalé comme
# probablement faux : le livre couvre une zone d'une trentaine de kilomètres.
RAYON_ALERTE_KM = 20.0


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #


def normalise(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation, pour comparer des noms."""
    texte = texte.replace("’", "'")
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = texte.lower()
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


def similarite(titre: str, nom: str) -> float:
    return difflib.SequenceMatcher(
        None, normalise(titre), normalise(nom)
    ).ratio()


def variantes(titre: str) -> list[str]:
    """Requêtes à tenter pour un titre, de la plus fidèle à la plus large."""
    base = titre.replace("’", "'")
    essais = [base]

    # « Circuit d'Arriélère » -> « Arriélère »,
    # « Vallée de la Gaoube » -> « Gaoube »
    prefixe = (
        r"^(circuit|vall[ée]e|cirque|lacs?|le|la|l'|les)\s+"
        r"(de\s+la\s+|de\s+l'|du\s+|des\s+|de\s+|d')?"
    )
    allege = re.sub(prefixe, "", base, flags=re.IGNORECASE).strip()
    if allege and normalise(allege) != normalise(base):
        essais.append(allege)

    essais.append(f"{base}, Hautes-Pyrénées")
    return essais


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance approchée, suffisante pour repérer un point hors zone."""
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def dans_bbox(lon: float, lat: float) -> bool:
    lon_min, lat_min, lon_max, lat_max = BBOX
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def http_json(url: str, params: dict, headers: dict, essais: int = 3):
    """GET JSON avec quelques tentatives ; renvoie None si l'appel échoue."""
    plein = f"{url}?{urllib.parse.urlencode(params)}"
    for tentative in range(essais):
        requete = urllib.request.Request(plein, headers=headers)
        try:
            with urllib.request.urlopen(requete, timeout=20) as reponse:
                return json.loads(reponse.read().decode("utf-8"))
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            json.JSONDecodeError,
            TimeoutError,
        ) as err:
            if tentative == essais - 1:
                print(f"    ! échec réseau ({err})", file=sys.stderr)
                return None
            time.sleep(1.5 * (tentative + 1))
    return None


def texte(valeur) -> str | None:
    """L'IGN renvoie parfois une liste (plusieurs communes) au lieu d'une
    chaîne."""
    if isinstance(valeur, list):
        valeur = ", ".join(str(v) for v in valeur if v)
    if valeur in (None, ""):
        return None
    return str(valeur)


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def cherche_ign(requete: str) -> list[dict]:
    """API Géoplateforme, index POI : toponymes de l'IGN."""
    data = http_json(
        IGN_URL,
        {
            "q": requete,
            "index": "poi",
            "limit": 10,
            "lon": CENTRE_LON,  # biais de proximité
            "lat": CENTRE_LAT,
        },
        {"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    time.sleep(IGN_DELAY)
    if not data:
        return []

    candidats = []
    for feature in data.get("features", []):
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        props = feature.get("properties") or {}
        nom = (
            texte(props.get("toponym"))
            or texte(props.get("toponyme"))
            or texte(props.get("label"))
            or texte(props.get("name"))
            or ""
        )
        candidats.append(
            {
                "lon": float(coords[0]),
                "lat": float(coords[1]),
                "nom": nom,
                "commune": texte(props.get("city"))
                or texte(props.get("commune")),
                "score": props.get("score"),
                "source": "ign",
            }
        )
    return candidats


def cherche_osm(requete: str) -> list[dict]:
    """Nominatim, borné à la zone du massif."""
    lon_min, lat_min, lon_max, lat_max = BBOX
    data = http_json(
        OSM_URL,
        {
            "q": requete,
            "format": "jsonv2",
            "limit": 10,
            "addressdetails": 1,
            "viewbox": f"{lon_min},{lat_max},{lon_max},{lat_min}",
            "bounded": 1,
        },
        {"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    time.sleep(OSM_DELAY)
    if not data:
        return []

    candidats = []
    for hit in data:
        adresse = hit.get("address") or {}
        commune = (
            adresse.get("village")
            or adresse.get("town")
            or adresse.get("municipality")
            or adresse.get("city")
        )
        candidats.append(
            {
                "lon": float(hit["lon"]),
                "lat": float(hit["lat"]),
                "nom": hit.get("name")
                or hit.get("display_name", "").split(",")[0],
                "commune": commune,
                "score": hit.get("importance"),
                "source": "osm",
            }
        )
    return candidats


# --------------------------------------------------------------------------- #
# Géocodage
# --------------------------------------------------------------------------- #


def meilleur(titre: str, candidats: list[dict]) -> dict | None:
    """Garde les candidats dans la zone et renvoie le mieux nommé."""
    retenus = []
    for cand in candidats:
        if not dans_bbox(cand["lon"], cand["lat"]):
            continue
        cand = dict(cand)
        cand["similarite"] = round(similarite(titre, cand["nom"] or ""), 3)
        retenus.append(cand)
    if not retenus:
        return None
    # Les scores IGN et OSM ne sont pas comparables : on classe d'abord sur
    # la ressemblance du nom, puis on préfère l'IGN, et le score ne sert
    # qu'à départager à l'intérieur d'une même source.
    retenus.sort(
        key=lambda c: (c["similarite"], c["source"] == "ign", c["score"] or 0),
        reverse=True,
    )
    return retenus[0]


def geocode(titre: str, cache: dict, bavard: bool = True) -> dict | None:
    """Cherche un titre dans l'IGN puis OSM ; renvoie le meilleur candidat.

    On interroge toutes les variantes de requête avant de trancher : s'arrêter
    à la première réponse acceptable ferait rater un meilleur candidat qu'une
    formulation plus courte aurait ramené. L'IGN reste prioritaire à
    ressemblance égale.
    """
    tous = []
    for source, chercheur in (("ign", cherche_ign), ("osm", cherche_osm)):
        for requete in variantes(titre):
            cle = f"{source}|{requete}"
            if cle not in cache:
                cache[cle] = chercheur(requete)
            tous.extend(cache[cle])

        # Inutile d'appeler OSM (1 req/s) si l'IGN a déjà une réponse franche.
        choix = meilleur(titre, tous)
        if choix is not None and choix["similarite"] >= SEUIL_SIMILARITE:
            break

    choix = meilleur(titre, tous)
    if bavard:
        if choix is None:
            print("    introuvable", file=sys.stderr)
        else:
            etat = (
                ""
                if choix["similarite"] >= SEUIL_SIMILARITE
                else "  ← douteux"
            )
            print(
                f"    {choix['source']} → {choix['nom']} "
                f"({choix['lat']:.5f}, {choix['lon']:.5f}) "
                f"sim={choix['similarite']}{etat}",
                file=sys.stderr,
            )
    return choix


def enrichir(rando: dict, choix: dict | None) -> dict:
    """Renvoie la rando avec les champs géo ajoutés à la fin."""
    sortie = dict(rando)
    if choix is None:
        sortie.update(
            lat=None,
            lon=None,
            geo_source=None,
            geo_nom=None,
            geo_commune=None,
            geo_similarite=None,
            geo_score=None,
        )
    else:
        sortie.update(
            lat=round(choix["lat"], 6),
            lon=round(choix["lon"], 6),
            geo_source=choix["source"],
            geo_nom=choix["nom"] or None,
            geo_commune=choix["commune"],
            geo_similarite=choix["similarite"],
            geo_score=choix["score"],
        )
    return sortie


# --------------------------------------------------------------------------- #


def main() -> int:
    parseur = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parseur.add_argument("entree", nargs="?", default="randos.json", type=Path)
    parseur.add_argument(
        "sortie", nargs="?", default="randos-geo.json", type=Path
    )
    parseur.add_argument(
        "--no-cache",
        action="store_true",
        help="ignore et réécrit .geocache.json",
    )
    parseur.add_argument(
        "--quiet", action="store_true", help="pas de détail par rando"
    )
    parseur.add_argument(
        "--overrides",
        type=Path,
        default=OVERRIDES_PATH,
        help="corrections manuelles par numéro (défaut : overrides.json)",
    )
    args = parseur.parse_args()

    randos = json.loads(args.entree.read_text(encoding="utf-8"))

    overrides = {}
    if args.overrides.exists():
        overrides = {
            str(numero): valeur
            for numero, valeur in json.loads(
                args.overrides.read_text(encoding="utf-8")
            ).items()
        }

    cache = {}
    if CACHE_PATH.exists() and not args.no_cache:
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}

    bavard = not args.quiet
    resultats, douteux, echecs = [], [], []

    for rando in randos:
        titre = rando.get("titre", "")
        numero = str(rando.get("numero"))
        if bavard:
            print(f"[{numero}] {titre}", file=sys.stderr)

        if numero in overrides:
            correction = overrides[numero]
            choix = {
                "lat": correction["lat"],
                "lon": correction["lon"],
                "nom": correction.get("nom", titre),
                "commune": correction.get("commune"),
                "score": None,
                "similarite": 1.0,
                "source": "manuel",
            }
            if bavard:
                print(
                    f"    manuel → {choix['nom']} "
                    f"({choix['lat']}, {choix['lon']})",
                    file=sys.stderr,
                )
        else:
            choix = geocode(titre, cache, bavard)

        resultats.append(enrichir(rando, choix))

        if choix is None:
            echecs.append(f"{numero} {titre}")
        elif choix["similarite"] < SEUIL_SIMILARITE:
            douteux.append(f"{numero} {titre}")

    # Points aberrants : loin du cœur du massif, ou tombés au même endroit
    # qu'une autre rando — les deux signes classiques d'un homonyme attrapé
    # par erreur.
    places = [r for r in resultats if r["lat"] is not None]
    aberrants, doublons = [], []
    if places:
        lat_med = statistics.median(r["lat"] for r in places)
        lon_med = statistics.median(r["lon"] for r in places)
        vus = {}
        for r in places:
            km = distance_km(r["lat"], r["lon"], lat_med, lon_med)
            if km > RAYON_ALERTE_KM:
                aberrants.append(
                    f"{r['numero']} {r['titre']} "
                    f"({km:.0f} km, {r['geo_commune']})"
                )
            cle = (r["lat"], r["lon"])
            if cle in vus:
                doublons.append(f"{vus[cle]} et {r['numero']} {r['titre']}")
            else:
                vus[cle] = f"{r['numero']} {r['titre']}"

    args.sortie.write_text(
        json.dumps(resultats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False), encoding="utf-8"
    )

    par_source = {}
    for r in resultats:
        par_source[r["geo_source"]] = par_source.get(r["geo_source"], 0) + 1

    print(f"\n{len(resultats)} randos → {args.sortie}", file=sys.stderr)
    print(
        "  ign: {i}   osm: {o}   manuel: {m}   sans coord.: {r}".format(
            i=par_source.get("ign", 0),
            o=par_source.get("osm", 0),
            m=par_source.get("manuel", 0),
            r=par_source.get(None, 0),
        ),
        file=sys.stderr,
    )
    for libelle, lignes in (
        (f"nom peu ressemblant (< {SEUIL_SIMILARITE})", douteux),
        (f"loin du massif (> {RAYON_ALERTE_KM:.0f} km)", aberrants),
        ("mêmes coordonnées", doublons),
        ("introuvables", echecs),
    ):
        if lignes:
            print(f"  {libelle} :", file=sys.stderr)
            for ligne in lignes:
                print(f"      {ligne}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
