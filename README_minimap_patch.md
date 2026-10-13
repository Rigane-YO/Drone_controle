# Mini-map radar 2D pour Drone_controle

Le patch ajoute un panneau de type radar en bas à gauche du visualiseur 3D.

- Affiche les liaisons et les zones dans une projection 2D vue du dessus (X/Z).
- Respecte les couleurs de zones définies dans la carte (`green`, `yellow`, `red`, `blue`, `cyan`, `orange`, `purple`, `magenta`, `pink`, `white`, `black`, `gray` ou `#RRGGBB`).
- Affiche les drones avec des marqueurs colorés qui se déplacent progressivement, en utilisant les positions interpolées du visualiseur 3D.
- Affiche le total de drones et le nombre livré.
- La touche **M** affiche/masque le radar.
- Crée `src/visualizer_3d.py.before-minimap.bak` avant la première modification, et vérifie la syntaxe Python avant d'écrire.
- Modifie uniquement `src/visualizer_3d.py`; aucun commit/push Git n'est effectué.

## Installation

Copier le ZIP à la racine du projet, puis depuis cette racine :

```bash
unzip -n drone_minimap_patch.zip
python scripts/apply_minimap_patch.py
python -m py_compile src/visualizer_3d.py
```

Lancer ensuite la simulation 3D comme d'habitude. Appuyer sur **M** pour masquer ou réafficher le radar.

Si le script annonce qu'une ancre est introuvable, il s'arrête sans écrire les modifications : la version locale du visualiseur est différente de celle prévue par le patch.
