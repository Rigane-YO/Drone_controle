#!/usr/bin/env python3
"""Change the existing 2D minimap to use the original map-file coordinates.

Run from the Drone_controle project root:
    python scripts/apply_minimap_map_coordinates_patch.py

Expected precondition: the earlier mini-map patch is already installed.
"""
from __future__ import annotations

import shutil
from pathlib import Path

TARGET = Path("src/visualizer_3d.py")
BACKUP = Path("src/visualizer_3d.py.before-minimap-map-layout.bak")
START = "    def _draw_minimap(self) -> None:\n"
END = "    def _draw_zone_overlays(self, camera: Any) -> None:\n"

NEW_METHOD = '''    def _draw_minimap(self) -> None:
        """Dessine un radar 2D basé sur les coordonnées x/y du fichier de carte.

        La disposition en anneaux utilisée par la scène 3D n'est jamais utilisée
        ici : le mini-map reproduit la géométrie définie dans le fichier .txt.
        """
        if (
            not getattr(self, "show_minimap", True)
            or self.app_state != STATE_SIMULATION
            or self.graph is None
            or self.simulator is None
            or not self.graph.zones
        ):
            return

        screen_w = pr.get_screen_width()
        screen_h = pr.get_screen_height()
        panel_w = min(300, max(190, int(screen_w * 0.27)))
        panel_h = min(210, max(145, int(screen_h * 0.26)))
        panel_x = 16
        panel_y = screen_h - panel_h - 16

        # Fond semi-transparent pour garder le radar lisible.
        pr.draw_rectangle(panel_x, panel_y, panel_w, panel_h, [3, 10, 19, 225])
        pr.draw_rectangle_lines(panel_x, panel_y, panel_w, panel_h, [0, 165, 210, 255])
        pr.draw_text("RADAR  /  CARTE 2D", panel_x + 11, panel_y + 7, 14, [70, 225, 255, 255])

        # IMPORTANT : utiliser Zone.x / Zone.y issus du fichier de carte,
        # pas self.node_positions (qui contient la disposition 3D en anneaux).
        map_points: Dict[str, Tuple[float, float]] = {
            name: (float(zone.x), float(zone.y))
            for name, zone in self.graph.zones.items()
        }
        xs = [point[0] for point in map_points.values()]
        ys = [point[1] for point in map_points.values()]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        range_x = max(max_x - min_x, 1.0)
        range_y = max(max_y - min_y, 1.0)

        inner_x = panel_x + 11
        inner_y = panel_y + 29
        inner_w = panel_w - 22
        inner_h = panel_h - 53

        # Une même échelle sur les deux axes conserve les proportions du plan.
        scale = min(inner_w / range_x, inner_h / range_y)
        map_draw_w = range_x * scale
        map_draw_h = range_y * scale
        offset_x = inner_x + (inner_w - map_draw_w) / 2.0
        offset_y = inner_y + (inner_h - map_draw_h) / 2.0

        # Grille discrète du radar.
        grid_color = [25, 52, 68, 180]
        for part in (1, 2, 3):
            gx = inner_x + int(inner_w * part / 4)
            gy = inner_y + int(inner_h * part / 4)
            pr.draw_line(gx, inner_y, gx, inner_y + inner_h, grid_color)
            pr.draw_line(inner_x, gy, inner_x + inner_w, gy, grid_color)

        def project_map(x: float, y: float) -> Tuple[int, int]:
            # On conserve l'orientation des coordonnées x/y du fichier.
            px = int(round(offset_x + (x - min_x) * scale))
            py = int(round(offset_y + (y - min_y) * scale))
            return px, py

        # Connexions projetées entre les coordonnées originales des zones.
        for connection in self.graph.connections_list:
            first = map_points.get(connection.zone1)
            second = map_points.get(connection.zone2)
            if first is None or second is None:
                continue
            x1, y1 = project_map(first[0], first[1])
            x2, y2 = project_map(second[0], second[1])
            pr.draw_line(x1, y1, x2, y2, [65, 88, 105, 255])

        # Zones/hubs à leur emplacement exact dans la carte source.
        for zone_name, map_pos in map_points.items():
            px, py = project_map(map_pos[0], map_pos[1])
            is_hub = zone_name in {
                self.simulator.start_hub, self.simulator.end_hub
            }
            radius = 5 if is_hub else 4
            pr.draw_circle(px, py, radius + 2, [4, 9, 15, 255])
            pr.draw_circle(px, py, radius, self._minimap_zone_color(zone_name))

        # Les marqueurs suivent les coordonnées de la carte, avec interpolation
        # 2D indépendante de l'animation 3D. Cela évite de projeter les anneaux.
        signature = tuple(sorted(
            (name, self.graph.zones[name].x, self.graph.zones[name].y)
            for name in self.graph.zones
        ))
        if getattr(self, "_minimap_map_signature", None) != signature:
            self._minimap_map_signature = signature
            self._minimap_drone_positions: Dict[str, List[float]] = {}
        elif not hasattr(self, "_minimap_drone_positions"):
            self._minimap_drone_positions = {}

        drone_palette = [
            [40, 235, 255, 255], [255, 175, 65, 255],
            [225, 105, 255, 255], [130, 255, 135, 255],
            [255, 235, 90, 255], [255, 105, 145, 255],
            [115, 160, 255, 255], [255, 255, 255, 255],
        ]
        for index, drone in enumerate(self.simulator.drones):
            zone_point = map_points.get(drone.current_location)
            if zone_point is None:
                continue
            target_x, target_y = zone_point
            current = self._minimap_drone_positions.get(drone.id)
            if current is None:
                current = [target_x, target_y]
            else:
                current = [
                    current[0] + (target_x - current[0]) * 0.22,
                    current[1] + (target_y - current[1]) * 0.22,
                ]
            self._minimap_drone_positions[drone.id] = current
            px, py = project_map(current[0], current[1])
            color = drone_palette[index % len(drone_palette)]
            pr.draw_circle(px, py, 6, [235, 245, 255, 235])
            pr.draw_circle(px, py, 4, color)

        delivered = sum(1 for drone in self.simulator.drones if drone.status == "delivered")
        footer = f"Drones : {len(self.simulator.drones)}   Livres : {delivered}"
        pr.draw_text(footer, panel_x + 10, panel_y + panel_h - 19, 10, [185, 205, 220, 255])

'''


def main() -> int:
    if not TARGET.is_file():
        print(f"ERREUR : {TARGET} introuvable.")
        print("Place ce script dans le projet et lance-le depuis la racine Drone_controle.")
        return 1

    original = TARGET.read_text(encoding="utf-8")
    if original.count(START) != 1 or original.count(END) != 1:
        print("ERREUR : méthode du mini-map non trouvée ou ambiguë.")
        print("Vérifie que le patch mini-map précédent est déjà installé.")
        print("Aucune modification effectuée.")
        return 1
    if original.index(END) < original.index(START):
        print("ERREUR : structure inattendue du visualiseur. Aucun changement effectué.")
        return 1

    prefix, rest = original.split(START, 1)
    _, suffix = rest.split(END, 1)
    updated = prefix + NEW_METHOD + END + suffix

    try:
        compile(updated, str(TARGET), "exec")
    except SyntaxError as error:
        print(f"ERREUR de syntaxe avant écriture : {error}")
        print("Aucune modification effectuée.")
        return 1

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print(f"Sauvegarde créée : {BACKUP}")
    else:
        print(f"Sauvegarde existante conservée : {BACKUP}")

    TARGET.write_text(updated, encoding="utf-8")
    print("Mini-map corrigé : il utilise maintenant Zone.x / Zone.y du fichier de carte.")
    print("La disposition en anneaux reste exclusive à la vue 3D.")
    print("Vérification de syntaxe Python : OK. Aucun commit/push effectué.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
