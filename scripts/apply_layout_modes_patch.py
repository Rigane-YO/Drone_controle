#!/usr/bin/env python3
"""Add switchable procedural/map-coordinate layouts to Drone_controle's 3D view.

Run from the project root:
    python scripts/apply_layout_modes_patch.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

TARGET = Path("src/visualizer_3d.py")
BACKUP = Path("src/visualizer_3d.py.before-layout-modes.bak")

MAP_LAYOUT_METHOD = '''    def _compute_map_layout(self) -> None:
        """Place zones using the original x/y coordinates from the map file.

        One uniform scale keeps the original proportions; map y is mapped to
        the 3D scene's z axis. This layout is deliberately flat (y = 0).
        """
        if self.graph is None:
            return

        zones = list(self.graph.zones.values())
        if not zones:
            return

        min_x = min(float(zone.x) for zone in zones)
        max_x = max(float(zone.x) for zone in zones)
        min_y = min(float(zone.y) for zone in zones)
        max_y = max(float(zone.y) for zone in zones)
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5

        # Fit both dimensions while preserving the aspect ratio of the map.
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)
        target_width = max(8.0, self.radius_x * 2.2)
        target_depth = max(8.0, self.radius_z * 2.2)
        scale = min(target_width / span_x, target_depth / span_y)

        for zone in zones:
            self.node_positions[zone.name] = [
                (float(zone.x) - center_x) * scale,
                0.0,
                (float(zone.y) - center_y) * scale,
            ]

    def _toggle_layout_mode(self) -> None:
        """Switch between the procedural 3D layout and the original map layout."""
        if self.graph is None or self.simulator is None:
            return

        self.layout_mode = "map" if self.layout_mode == "custom" else "custom"
        self.node_positions.clear()
        self.drone_trails.clear()
        self._camera_transition = None
        self.follow_drone_id = None
        self.hovered_zone = None
        self._compute_3d_layout()

        # Reframe the whole network after a layout switch. Map coordinates can
        # be much wider than the procedural ring layout, so fit the X extent too.
        height_step = max(3.2, self.planet_size * 1.7)
        map_distance = self.radius_x * 2.3 if self.layout_mode == "map" else 0.0
        self._home_cam_distance = max(
            35.0, self.radius_z * 2.2, map_distance, height_step * 5.0
        )
        self.cam_distance = self._home_cam_distance
        self.cam_yaw = 0.0
        self.cam_pitch = 0.95

        # Preserve the simulator's real drone locations while moving their
        # render positions to the new layout. Simulation state is untouched.
        self.drone_positions.clear()
        for drone in self.simulator.drones:
            node_pos = self.node_positions.get(
                drone.current_location,
                self.node_positions.get(self.simulator.start_hub, [0.0, 0.0, 0.0]),
            )
            self.drone_positions[drone.id] = [
                node_pos[0], node_pos[1] + self.planet_size * 0.5, node_pos[2]
            ]

'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected exactly one matching code block, found {count}")
    return source.replace(old, new, 1)


def apply_patch_to_source(source: str) -> str:
    """Patch source text. Raises ValueError rather than guessing if anchors differ."""
    result = source

    # Initial mode value must exist before the first _setup_layout() call.
    if 'self.layout_mode = "custom"' not in result:
        result = replace_once(
            result,
            "        self.show_connections = True\n",
            '        self.show_connections = True\n\n'
            '        # "custom" = procedural rings/height levels; "map" = map x/y.\n'
            '        self.layout_mode = "custom"\n',
            "initial layout mode",
        )

    # The initial framing needs to accommodate wide maps in map-coordinate mode.
    old_camera = '''        self.cam_distance = max(
            35.0,
            self.radius_z * 2.2,
            _height_step_for_view * 5.0,
        )
'''
    new_camera = '''        _map_width_for_view = (
            self.radius_x * 2.3 if self.layout_mode == "map" else 0.0
        )
        self.cam_distance = max(
            35.0,
            self.radius_z * 2.2,
            _map_width_for_view,
            _height_step_for_view * 5.0,
        )
'''
    if new_camera not in result:
        result = replace_once(result, old_camera, new_camera, "camera framing")

    # Route _compute_3d_layout to either the generated or coordinate layout.
    guard = '''    def _compute_3d_layout(self) -> None:
        """Répartit les planètes sur plusieurs anneaux concentriques."""
        if not self.graph or not self.simulator:
            return
'''
    guard_new = guard + '''
        if self.layout_mode == "map":
            self._compute_map_layout()
            return
'''
    if "if self.layout_mode == \"map\":\n            self._compute_map_layout()" not in result:
        result = replace_once(result, guard, guard_new, "layout dispatch")

    # Add coordinate placement and mode switching methods.
    if "    def _compute_map_layout(self) -> None:\n" not in result:
        result = replace_once(
            result,
            "    def _init_drones(self) -> None:\n",
            MAP_LAYOUT_METHOD + "    def _init_drones(self) -> None:\n",
            "layout methods insertion",
        )

    # Add the keyboard shortcut, leaving existing controls unchanged.
    key_anchor = '''                if pr.is_key_pressed(pr.KEY_M):
                    self.show_minimap = not self.show_minimap
'''
    key_replacement = key_anchor + '''                if pr.is_key_pressed(pr.KEY_V):
                    self._toggle_layout_mode()
'''
    if "if pr.is_key_pressed(pr.KEY_V):\n                    self._toggle_layout_mode()" not in result:
        result = replace_once(result, key_anchor, key_replacement, "V keyboard shortcut")

    # Add a layout selector to the Options menu and move speed controls down.
    old_options = '''        speed_label = f"VITESSE DE SIMULATION : {self.step_interval:.2f}s / tour"
        pr.draw_text(speed_label, 60, 260, 20, COLOR_WHITE)
        self._draw_speed_slider(60, 302, 320)
        pr.draw_text("L : noms | K : jauges | T : traînées", 60, 340, 16, COLOR_GRAY)
        pr.draw_text(
            "F : suivre drone | R : caméra | RETOUR : annuler un tour",
            60, 365, 16, COLOR_GRAY
        )
'''
    new_options = '''        layout_label = (
            "3D PERSONNALISÉE"
            if self.layout_mode == "custom"
            else "COORDONNÉES CARTE"
        )
        if self._draw_button(
            (60, 250, 450, 45), f"DISPOSITION : {layout_label}"
        ):
            self._toggle_layout_mode()

        speed_label = f"VITESSE DE SIMULATION : {self.step_interval:.2f}s / tour"
        pr.draw_text(speed_label, 60, 320, 20, COLOR_WHITE)
        self._draw_speed_slider(60, 362, 320)
        pr.draw_text("L : noms | K : jauges | T : traînées", 60, 400, 16, COLOR_GRAY)
        pr.draw_text(
            "V : disposition | M : mini-map | F : suivre drone | R : caméra",
            60, 425, 16, COLOR_GRAY
        )
        pr.draw_text(
            "RETOUR ARRIÈRE : annuler un tour",
            60, 450, 16, COLOR_GRAY
        )
'''
    if "f\"DISPOSITION : {layout_label}\"" not in result:
        result = replace_once(result, old_options, new_options, "Options menu selector")

    # Show the current visual mode in the simulation HUD.
    hud_anchor = '''                pr.draw_text(f"Tour : {self.simulator.turn}", 20, 45, 22, COLOR_WHITE)
'''
    hud_new = hud_anchor + '''                layout_hud = (
                    "3D PERSONNALISÉE"
                    if self.layout_mode == "custom"
                    else "COORDONNÉES CARTE"
                )
                pr.draw_text(
                    f"Disposition : {layout_hud} (V)",
                    20, 70, 14, COLOR_GRAY,
                )
'''
    if 'f"Disposition : {layout_hud} (V)"' not in result:
        result = replace_once(result, hud_anchor, hud_new, "mode HUD label")

    compile(result, str(TARGET), "exec")
    return result


def main() -> int:
    if not TARGET.is_file():
        print(f"ERREUR : {TARGET} introuvable.")
        print("Lance cette commande depuis la racine du projet Drone_controle.")
        return 1

    source = TARGET.read_text(encoding="utf-8")
    try:
        patched = apply_patch_to_source(source)
    except (ValueError, SyntaxError) as error:
        print(f"Patch annulé : {error}")
        print("Aucun fichier n'a été modifié. Vérifie ta version de visualizer_3d.py.")
        return 1

    if patched == source:
        print("Le patch est déjà appliqué. Aucun changement nécessaire.")
        return 0

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print(f"Sauvegarde créée : {BACKUP}")
    else:
        print(f"Sauvegarde précédente conservée : {BACKUP}")

    TARGET.write_text(patched, encoding="utf-8")
    print("Patch appliqué avec succès à src/visualizer_3d.py.")
    print("  - Touche V : basculer entre disposition 3D et coordonnées de la carte.")
    print("  - Menu Options : même réglage accessible avec un bouton.")
    print("  - Changement de mode : caméra et drones repositionnés sans modifier la simulation.")
    print("  - Mini-map : reste basé sur les coordonnées originales de la carte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
