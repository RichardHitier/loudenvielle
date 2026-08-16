# Randos

44 randonnées des Pyrénées (Gavarnie, Luz, Barèges, Néouvielle, vallée
d'Aure), géocodées puis affichées sur une carte imprimable.

## Ouvrir la carte

Ouvrir `carte.html` dans un navigateur — double-clic suffit, il n'y a pas
de serveur à lancer. Les données sont injectées dans la page, parce qu'un
navigateur refuse de lire un JSON voisin en `file://`.

- Les points sont colorés par niveau et portent leur numéro.
- Un clic sur un point ouvre sa fiche : page, temps de montée, temps
  total, boucle ou non.
- Le panneau de gauche n'affiche qu'un niveau à la fois, et la liste est
  ordonnée par temps total croissant.
- « Imprimer / PDF » sort une carte A4 avec sa légende, puis le tableau
  des fiches. Le bouton attend le chargement des tuiles ; `Ctrl+P` direct
  se contente de ce qui est en cache.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `randos.json` | la saisie de départ, sans coordonnées |
| `geocode_randos.py` | géocode les titres (IGN, puis Nominatim en secours) |
| `overrides.json` | corrections manuelles, avec leur justification |
| `randos-geo.json` | les randos avec `lat`/`lon` et champs de diagnostic |
| `carte.template.html` | la page — c'est elle qu'on édite |
| `build_carte.py` | injecte les données dans le template |
| `carte.html` | la page à ouvrir (générée) |
| `build_pdfs.py` | produit les cinq feuilles PDF |
| `pdf/` | les feuilles prêtes à imprimer (générées) |

## Les feuilles PDF

`pdf/` contient cinq feuilles d'une page chacune :

- quatre cartes en paysage, une par niveau, points colorés et numérotés ;
- une liste en portrait — numéro, titre, temps total, page — dans l'ordre
  des temps croissants.

## Régénérer

```sh
python3 geocode_randos.py   # randos.json     -> randos-geo.json
python3 build_carte.py      # randos-geo.json -> carte.html
python3 build_pdfs.py       # carte.html      -> pdf/*.pdf
```

`build_pdfs.py` pilote un Chrome sans interface : la page se met en
configuration d'export via son URL (`?feuille=carte&niveau=Marcheur`,
`?feuille=liste`), attend ses tuiles, et le navigateur imprime.

Le géocodage garde ses réponses dans `.geocache.json` pour ne pas
retaper les API à chaque essai.

## Sur le géocodage

Les toponymes de montagne ont beaucoup d'homonymes, et un géocodeur qui
répond à tous les coups ne dit rien de sa justesse : le premier passage
trouvait les 44 titres, dont 6 au mauvais endroit — le Cirque du Lis de
Cauterets au lieu de celui de Gavarnie, le Pic Arrouy de Luchon au lieu
du Mont Arrouy de Betpouey, deux randos sur le même point.

Le script signale donc les deux symptômes d'un homonyme attrapé par
erreur : un point à plus de 20 km de la médiane du massif, et deux randos
aux mêmes coordonnées. Les corrections vivent dans `overrides.json`,
chacune avec la raison qui l'a motivée.

## Sources

Fonds de carte : [IGN Géoplateforme](https://geoservices.ign.fr/) et
[OpenTopoMap](https://opentopomap.org/) (données OpenStreetMap).
Géocodage : IGN Géoplateforme et
[Nominatim](https://nominatim.openstreetmap.org/).
Cartographie : [Leaflet](https://leafletjs.com/).
