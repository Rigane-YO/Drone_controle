#!/usr/bin/env python3
"""Add a small 2D radar/minimap to the Drone_controle 3D visualizer.

Run from the project root:
    python scripts/apply_minimap_patch.py

The patch is local-only, idempotent, validates Python syntax before writing,
and keeps a one-time backup of src/visualizer_3d.py.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

TARGET = Path("src/visualizer_3d.py")
BACKUP = Path("src/visualizer_3d.py.before-minimap.bak")

MINIMAP_METHODS = '''    def _minimap_zone_color(self, zone_name: str) -> List[int]:
        """Couleur 2D de la zone : conserve d'abord la couleur de la carte."""
        zone = self.graph.get_zone(zone_name) if self.graph is not None else None
        if zone is not None and zone.color:
            raw = zone.color.strip().lower()
            named_colors = {
                "green": [60, 230, 130, 255],
                "yellow": [255, 220, 60, 255],
                "red": [255, 75, 85, 255],
                "blue": [70, 150, 255, 255],
                "cyan": [40, 225, 255, 255],
                "orange": [255, 155, 60, 255],
                "purple": [190, 100, 255, 255],
                "magenta": [255, 80, 205, 255],
                "pink": [255, 125, 190, 255],
                "white": [245, 245, 245, 255],
                "black": [90, 100, 115, 255],
                "gray": [155, 165, 180, 255],
                "grey": [155, 165, 180, 255],
            }
            if raw in named_colors:
                return named_colors[raw]
            if raw.startswith("#") and len(raw) == 7:
                try:
                    return [int(raw[1:3], 16), int(raw[3:5], 16), int(raw[5:7], 16), 255]
                except ValueError:
                    pass

        if zone_name == getattr(self.simulator, "start_hub", None):
            return [65, 175, 255, 255]
        if zone_name == getattr(self.simulator, "end_hub", None):
            return [255, 95, 110, 255]
        if zone is not None:
            if zone.zone_type == "priority":
                return [210, 105, 255, 255]
            if zone.zone_type == "restricted":
                return [255, 170, 65, 255]
            if zone.zone_type == "blocked":
                return [255, 70, 80, 255]
        return [125, 165, 190, 255]

    def _draw_minimap(self) -> None:
        """Dessine un radar 2D en bas à gauche, par-dessus la scène 3D."""
        if (
            not getattr(self, "show_minimap", True)
            or self.app_state != STATE_SIMULATION
            or self.graph is None
            or self.simulator is None
            or not self.node_positions
        ):
            return

        screen_w = pr.get_screen_width()
        screen_h = pr.get_screen_height()
        panel_w = min(300, max(190, int(screen_w * 0.27)))
        panel_h = min(210, max(145, int(screen_h * 0.26)))
        panel_x = 16
        panel_y = screen_h - panel_h - 16

        # Fond semi-transparent pour rester lisible sur le fond animé.
        pr.draw_rectangle(panel_x, panel_y, panel_w, panel_h, [3, 10, 19, 225])
        pr.draw_rectangle_lines(panel_x, panel_y, panel_w, panel_h, [0, 165, 210, 255])
        pr.draw_text("RADAR  /  VUE 2D", panel_x + 11, panel_y + 7, 14, [70, 225, 255, 255])

        point_values = list(self.node_positions.values())
        min_x = min(point[0] for point in point_values)
        max_x = max(point[0] for point in point_values)
        min_z = min(point[2] for point in point_values)
        max_z = max(point[2] for point in point_values)
        range_x = max(max_x - min_x, 1.0)
        range_z = max(max_z - min_z, 1.0)

        inner_x = panel_x + 11
        inner_y = panel_y + 29
        inner_w = panel_w - 22
        inner_h = panel_h - 53

        # Grille légère, comme un radar de jeu.
        grid_color = [25, 52, 68, 180]
        for part in (1, 2, 3):
            gx = inner_x + int(inner_w * part / 4)
            gy = inner_y + int(inner_h * part / 4)
            pr.draw_line(gx, inner_y, gx, inner_y + inner_h, grid_color)
            pr.draw_line(inner_x, gy, inner_x + inner_w, gy, grid_color)

        def project(world_pos: List[float]) -> Tuple[int, int]:
            px = inner_x + int(((world_pos[0] - min_x) / range_x) * inner_w)
            # Top-down view: world Z increases downward on the radar.
            py = inner_y + int(((max_z - world_pos[2]) / range_z) * inner_h)
            return px, py

        # Les liaisons restent discrètes; les couleurs des zones suivent la carte.
        for connection in self.graph.connections_list:
            first = self.node_positions.get(connection.zone1)
            second = self.node_positions.get(connection.zone2)
            if first is None or second is None:
                continue
            x1, y1 = project(first)
            x2, y2 = project(second)
            pr.draw_line(x1, y1, x2, y2, [65, 88, 105, 255])

        # Zones/hubs.
        for zone_name, world_pos in self.node_positions.items():
            px, py = project(world_pos)
            is_hub = zone_name in {
                self.simulator.start_hub, self.simulator.end_hub
            }
            radius = 5 if is_hub else 4
            pr.draw_circle(px, py, radius + 2, [4, 9, 15, 255])
            pr.draw_circle(px, py, radius, self._minimap_zone_color(zone_name))

        # Les positions 3D interpolées sont projetées sur X/Z : les marqueurs
        # se déplacent en continu au lieu de sauter d'un nœud à l'autre.
        drone_palette = [
            [40, 235, 255, 255], [255, 175, 65, 255],
            [225, 105, 255, 255], [130, 255, 135, 255],
            [255, 235, 90, 255], [255, 105, 145, 255],
            [115, 160, 255, 255], [255, 255, 255, 255],
        ]
        for index, drone in enumerate(self.simulator.drones):
            world_pos = self.drone_positions.get(drone.id)
            if world_pos is None:
                continue
            px, py = project(world_pos)
            color = drone_palette[index % len(drone_palette)]
            pr.draw_circle(px, py, 6, [235, 245, 255, 235])
            pr.draw_circle(px, py, 4, color)

        delivered = sum(1 for drone in self.simulator.drones if drone.status == "delivered")
        footer = f"Drones : {len(self.simulator.drones)}   Livres : {delivered}"
        pr.draw_text(footer, panel_x + 10, panel_y + panel_h - 19, 10, [185, 205, 220, 255])

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"Ancre {label!r} introuvable ou ambiguë (occurrences={count}).")
    return text.replace(old, new, 1)


def main() -> int:
    if not TARGET.is_file():
        print(f"ERREUR : {TARGET} introuvable. Lance le script depuis la racine du projet.")
        return 1

    original = TARGET.read_text(encoding="utf-8")
    updated = original
    changes: list[str] = []

    # Default visible; M toggles the radar on/off.
    if "self.show_minimap = True" not in updated:
        init_anchor = "        self.show_connections = True\n"
        if updated.count(init_anchor) != 1:
            print("ERREUR : ancre d'initialisation des options introuvable/ambiguë. Aucun fichier modifié.")
            return 1
        updated = updated.replace(
            init_anchor,
            init_anchor + "        self.show_minimap = True  # Radar 2D (touche M)\n",
            1,
        )
        changes.append("activation du radar par défaut")

    if "pr.is_key_pressed(pr.KEY_M)" not in updated:
        key_anchor = "                if pr.is_key_pressed(pr.KEY_BACKSPACE) and self.simulator:\n"
        if updated.count(key_anchor) != 1:
            print("ERREUR : ancre clavier introuvable/ambiguë. Aucun fichier modifié.")
            return 1
        updated = updated.replace(
            key_anchor,
            "                if pr.is_key_pressed(pr.KEY_M):\n"
            "                    self.show_minimap = not self.show_minimap\n\n" + key_anchor,
            1,
        )
        changes.append("raccourci M pour afficher/masquer le radar")

    if "    def _draw_minimap(self) -> None:" not in updated:
        method_anchor = "    def _draw_zone_overlays(self, camera: Any) -> None:\n"
        if updated.count(method_anchor) != 1:
            print("ERREUR : méthode d'affichage des zones introuvable/ambiguë. Aucun fichier modifié.")
            return 1
        updated = updated.replace(method_anchor, MINIMAP_METHODS + method_anchor, 1)
        changes.append("ajout du mini-map 2D avec positions animées des drones")

    if "            self._draw_minimap()" not in updated:
        draw_anchor = "            self._draw_zone_overlays(camera)\n"
        if updated.count(draw_anchor) != 1:
            print("ERREUR : point d'insertion du radar dans la scène introuvable/ambigu. Aucun fichier modifié.")
            return 1
        updated = updated.replace(
            draw_anchor,
            draw_anchor + "            self._draw_minimap()\n",
            1,
        )
        changes.append("rendu du radar en surimpression 2D")

    if not changes:
        print("Aucune modification nécessaire : le mini-map semble déjà installé.")
        return 0

    try:
        compile(updated, str(TARGET), "exec")
    except SyntaxError as error:
        print(f"ERREUR de syntaxe avant écriture : {error}. Aucun fichier modifié.")
        return 1

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print(f"Sauvegarde créée : {BACKUP}")
    else:
        print(f"Sauvegarde existante conservée : {BACKUP}")

    TARGET.write_text(updated, encoding="utf-8")
    print("Patch appliqué :")
    for change in changes:
        print(f"  ✓ {change}")
    print("Vérification syntaxique : OK")
    print("Raccourci : M affiche/masque le radar. Aucun commit ou push n'a été effectué.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
