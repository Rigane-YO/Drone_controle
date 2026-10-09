#!/usr/bin/env python3
"""Upgrade the existing Fly-in viewer and simulator with visual/UX features.

Run from the repository root. Changes are anchor-checked, backed up, and
idempotent. This script intentionally keeps the existing renderer structure.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Callable

ROOT = Path.cwd()
VIEWER = ROOT / "src" / "visualizer_3d.py"
SIMULATOR = ROOT / "src" / "simulation.py"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count == 0:
        if new.strip() and new.strip() in source:
            return source
        raise ValueError(f"Ancre introuvable pour : {label}")
    if count != 1:
        raise ValueError(f"Ancre ambiguë pour {label} ({count} occurrences)")
    return source.replace(old, new, 1)


def insert_after(source: str, anchor: str, addition: str, label: str) -> str:
    return replace_once(source, anchor, anchor + addition, label)


def patch_simulator(source: str) -> str:
    """Add a bounded history stack and a public undo_step() API."""
    if "class _SimulatorSnapshot:" in source and "def undo_step(self) -> bool:" in source:
        return source

    source = replace_once(
        source,
        "from typing import Dict, List, Optional, Tuple\n\nfrom graph import NetworkGraph\n",
        "from dataclasses import dataclass\nfrom typing import Dict, List, Optional, Tuple\n\nfrom graph import NetworkGraph\n",
        "imports simulateur",
    )

    snapshot_types = '''\n\n@dataclass\nclass _DroneSnapshot:\n    current_location: str\n    path: List[str]\n    status: str\n    turns_spent_in_zone: int\n\n\n@dataclass\nclass _SimulatorSnapshot:\n    turn: int\n    drones: List[_DroneSnapshot]\n    zone_occupancy: Dict[str, int]\n    error: Optional[str]\n    deadlocked: bool\n    waited_this_turn: bool\n'''
    source = insert_after(source, "from models import Drone\n", snapshot_types, "types snapshot")

    source = insert_after(
        source,
        "        self.deadlocked = False\n        self._waited_this_turn = False\n",
        "        # Historique borné pour permettre un retour en arrière sans\n"
        "        # conserver une quantité de mémoire illimitée.\n"
        "        self._history: List[_SimulatorSnapshot] = []\n",
        "initialisation historique",
    )

    step_anchor = '''        if self.is_finished() or self.deadlocked:\n            return []\n\n        self.turn += 1\n'''
    step_replacement = '''        if self.is_finished() or self.deadlocked:\n            return []\n\n        self._history.append(self._capture_snapshot())\n        if len(self._history) > 1000:\n            del self._history[0]\n        self.turn += 1\n'''
    source = replace_once(source, step_anchor, step_replacement, "historique avant chaque tour")

    run_anchor = "    def run(self) -> bool:\n"
    history_methods = '''    def _capture_snapshot(self) -> _SimulatorSnapshot:\n        """Copie l'état mutable nécessaire pour annuler un tour."""\n        drone_states = [\n            _DroneSnapshot(\n                current_location=drone.current_location,\n                path=list(drone.path),\n                status=drone.status,\n                turns_spent_in_zone=drone.turns_spent_in_zone,\n            )\n            for drone in self.drones\n        ]\n        return _SimulatorSnapshot(\n            turn=self.turn,\n            drones=drone_states,\n            zone_occupancy=dict(self.zone_occupancy),\n            error=self.error,\n            deadlocked=self.deadlocked,\n            waited_this_turn=self._waited_this_turn,\n        )\n\n    def undo_step(self) -> bool:\n        """Restaure l'état précédant le dernier appel à step()."""\n        if not self._history:\n            return False\n\n        snapshot = self._history.pop()\n        self.turn = snapshot.turn\n        for drone, saved in zip(self.drones, snapshot.drones):\n            drone.current_location = saved.current_location\n            drone.path = list(saved.path)\n            drone.status = saved.status\n            drone.turns_spent_in_zone = saved.turns_spent_in_zone\n        self.zone_occupancy = dict(snapshot.zone_occupancy)\n        self.error = snapshot.error\n        self.deadlocked = snapshot.deadlocked\n        self._waited_this_turn = snapshot.waited_this_turn\n        return True\n\n'''
    source = replace_once(
        source, run_anchor, history_methods + run_anchor, "API retour arrière"
    )
    return source


def patch_viewer(source: str) -> str:
    """Apply the rendering, HUD, camera, performance and control improvements."""
    # If all feature entry points are already present, this is a no-op.
    if "def _draw_zone_overlays(self, camera: Any) -> None:" in source and "def _draw_hub_ring" in source and "self._undo_simulation()" in source:
        return source

    source = replace_once(
        source,
        "import math\nimport os\nimport time\nfrom typing import Dict, List, Optional, Tuple\n",
        "import math\nimport os\nimport time\nfrom typing import Any, Dict, List, Optional, Tuple\n",
        "imports visualiseur",
    )

    fields_anchor = '''        self.show_capacity_info = False  # Flag --capacity-info\n        self.step_interval = 0.8         # Vitesse de simulation\n        self.show_connections = True\n'''
    fields_replacement = fields_anchor + '''\n        # Affichage interactif et diagnostic de la scène.\n        self.show_zone_labels = False\n        self.show_capacity_gauges = False\n        self.show_trails = True\n        self.follow_drone_id: Optional[str] = None\n        self.hovered_zone: Optional[str] = None\n        self.drone_trails: Dict[str, List[List[float]]] = {}\n        self.render_frame_index = 0\n        self.last_moves: List[str] = []\n        self._speed_slider_dragging = False\n        self._camera_transition: Optional[Tuple[float, float, float, float, float]] = None\n'''
    source = replace_once(source, fields_anchor, fields_replacement, "état visuel")

    layout_anchor = '''        self.cam_distance = max(35.0, self.radius_z * 2.2)\n        self.cam_yaw = 0.0\n        self.cam_pitch = 0.95\n'''
    source = insert_after(
        source,
        layout_anchor,
        "        self._home_cam_distance = self.cam_distance\n"
        "        self.follow_drone_id = None\n"
        "        self._camera_transition = None\n"
        "        self.drone_trails.clear()\n"
        "        self.show_trails = self.num_nodes < 24\n"
        "        self.last_moves = []\n",
        "réinitialisation caméra et trails",
    )

    # Replace the low-level model loader to optionally select an exported low-poly GLB.
    loader_old = '''    def _load_planet_model(self):\n        """Charge assets/planet.glb (planète volcanique). Retourne None si absent."""\n        path = os.path.join("assets", "planet.glb")\n        if os.path.exists(path):\n            try:\n                return pr.load_model(path)\n            except Exception as e:\n                print(f"⚠ Erreur modèle planète : {e}")\n        return None\n'''
    loader_new = '''    def _load_planet_model(self, low_detail: bool = False) -> Any:\n        """Charge un modèle; les grandes cartes peuvent utiliser planet_low.glb."""\n        normal_path = os.path.join("assets", "planet.glb")\n        low_path = os.path.join("assets", "planet_low.glb")\n        path = low_path if low_detail and os.path.exists(low_path) else normal_path\n        if os.path.exists(path):\n            try:\n                return pr.load_model(path)\n            except Exception as e:\n                print(f"⚠ Erreur modèle planète ({path}) : {e}")\n        return None\n'''
    source = replace_once(source, loader_old, loader_new, "LOD planète")

    # Helpers inserted before model loading. They keep API compatibility with PyRay.
    helpers_anchor = loader_new
    helpers = '''
    @staticmethod
    def _edge_key(zone1: str, zone2: str) -> Tuple[str, str]:
        return (zone1, zone2) if zone1 <= zone2 else (zone2, zone1)

    def _pending_link_load(self, zone1: str, zone2: str) -> int:
        """Compte les drones dont le prochain déplacement vise cette liaison."""
        if self.simulator is None:
            return 0
        key = self._edge_key(zone1, zone2)
        return sum(
            1 for drone in self.simulator.drones
            if drone.status != "delivered" and drone.path
            and self._edge_key(drone.current_location, drone.path[0]) == key
        )

    @staticmethod
    def _connection_color(load_ratio: float) -> List[int]:
        """Couleur informative : cyan peu chargé, ambre chargé, rouge saturé."""
        if load_ratio >= 1.0:
            return [255, 70, 90, 230]
        if load_ratio >= 0.66:
            return [255, 185, 45, 220]
        if load_ratio >= 0.33:
            return [35, 205, 255, 210]
        return [65, 105, 170, 190]

    def _draw_hub_ring(
        self, center: List[float], radius: float, color: List[int]
    ) -> None:
        """Dessine deux anneaux fins autour d'un hub, sans teinter la lave."""
        for ring_radius, segments, height in (
            (radius, 24, center[1] + radius * 0.04),
            (radius * 1.18, 20, center[1] + radius * 0.06),
        ):
            previous = [
                center[0] + ring_radius, height, center[2]
            ]
            for index in range(1, segments + 1):
                angle = 2.0 * math.pi * index / segments
                current = [
                    center[0] + math.cos(angle) * ring_radius,
                    height,
                    center[2] + math.sin(angle) * ring_radius,
                ]
                pr.draw_line_3d(previous, current, color)
                previous = current

    def _set_camera_view(self, yaw: float, pitch: float) -> None:
        """Anime un changement de vue clavier sur une courte transition."""
        self._camera_transition = (
            self.cam_yaw, self.cam_pitch, yaw, pitch, time.time()
        )

    def _reset_camera(self) -> None:
        self.follow_drone_id = None
        self._set_camera_view(0.0, 0.95)
        self.cam_distance = getattr(self, "_home_cam_distance", 35.0)

    def _cycle_follow_drone(self) -> None:
        if self.simulator is None or not self.simulator.drones:
            self.follow_drone_id = None
            return
        drone_ids = [drone.id for drone in self.simulator.drones]
        if self.follow_drone_id not in drone_ids:
            self.follow_drone_id = drone_ids[0]
            return
        current_follow = self.follow_drone_id
        if current_follow is None:
            self.follow_drone_id = drone_ids[0]
            return
        current_index = drone_ids.index(current_follow)
        self.follow_drone_id = drone_ids[(current_index + 1) % len(drone_ids)]

    def _advance_simulation(self) -> None:
        """Avance d'un tour via l'API publique du moteur."""
        if self.simulator is None or self.simulator.deadlocked:
            self.simulation_running = False
            return
        self.last_moves = self.simulator.step()
        if self.simulator.deadlocked:
            self.simulation_running = False

    def _undo_simulation(self) -> None:
        """Annule le dernier tour et réaligne visuellement les drones."""
        if self.simulator is None or not self.simulator.undo_step():
            return
        self.last_moves = []
        self.simulation_running = False
        self.drone_trails.clear()
        for drone in self.simulator.drones:
            node_pos = self.node_positions.get(drone.current_location)
            if node_pos is not None:
                self.drone_positions[drone.id] = [
                    node_pos[0], node_pos[1] + self.planet_size * 0.5, node_pos[2]
                ]

    def _track_drone_trail(self, drone_id: str, position: List[float]) -> None:
        trail = self.drone_trails.setdefault(drone_id, [])
        if not trail or sum(
            (position[axis] - trail[-1][axis]) ** 2 for axis in range(3)
        ) >= 0.0064:
            trail.append(list(position))
        if len(trail) > 18:
            del trail[:-18]

    def _pick_hovered_zone(self, camera: Any) -> Optional[str]:
        mouse = pr.get_mouse_position()
        closest_name: Optional[str] = None
        closest_distance = float("inf")
        hit_radius = max(16.0, self.planet_size * 5.0)
        for zone_name, position in self.node_positions.items():
            screen = pr.get_world_to_screen(position, camera)
            distance = math.hypot(mouse.x - screen.x, mouse.y - screen.y)
            if distance <= hit_radius and distance < closest_distance:
                closest_name = zone_name
                closest_distance = distance
        return closest_name

    def _draw_zone_overlays(self, camera: Any) -> None:
        """Dessine les noms et jauges après la scène 3D pour rester lisibles."""
        if self.graph is None or self.simulator is None:
            return
        occupancy = {name: 0 for name in self.graph.zones}
        delivered_at_goal = 0
        for drone in self.simulator.drones:
            if drone.status == "delivered":
                delivered_at_goal += 1
            else:
                current = drone.current_location
                occupancy[current] = occupancy.get(current, 0) + 1

        for zone_name, position in self.node_positions.items():
            hovered = zone_name == self.hovered_zone
            if not (self.show_zone_labels or self.show_capacity_gauges or hovered):
                continue
            screen = pr.get_world_to_screen(position, camera)
            x, y = int(screen.x), int(screen.y)
            zone = self.graph.get_zone(zone_name)
            if zone is None:
                continue

            if self.show_zone_labels or hovered:
                label_width = pr.measure_text(zone_name, 15)
                label_x = x - label_width // 2
                label_y = y - 27
                pr.draw_rectangle(
                    label_x - 5, label_y - 3, label_width + 10, 21, [4, 12, 25, 210]
                )
                color = COLOR_YELLOW if hovered else COLOR_WHITE
                pr.draw_text(zone_name, label_x, label_y, 15, color)

            if self.show_capacity_gauges or hovered:
                is_goal = zone_name == self.simulator.end_hub
                is_start = zone_name == self.simulator.start_hub
                if is_goal:
                    amount = delivered_at_goal
                    capacity = max(1, self.simulator.nb_drones)
                    counter_text = f"Arrivés {amount}/{self.simulator.nb_drones}"
                elif is_start:
                    amount = occupancy.get(zone_name, 0)
                    capacity = max(1, self.simulator.nb_drones)
                    counter_text = f"Départ {amount}/{self.simulator.nb_drones}"
                else:
                    amount = occupancy.get(zone_name, 0)
                    capacity = max(1, zone.max_drones)
                    counter_text = f"{amount}/{zone.max_drones} drones"
                text_width = pr.measure_text(counter_text, 12)
                gauge_x = x - 32
                gauge_y = y + 5
                pr.draw_text(counter_text, x - text_width // 2, gauge_y, 12, COLOR_WHITE)
                pr.draw_rectangle(
                    gauge_x, gauge_y + 15, 64, 5, [45, 55, 70, 230]
                )
                fill_width = int(64 * min(1.0, amount / capacity))
                if amount >= capacity and not is_goal and not is_start:
                    gauge_color = [255, 75, 85, 255]
                else:
                    gauge_color = [40, 220, 150, 255]
                if fill_width > 0:
                    pr.draw_rectangle(
                        gauge_x, gauge_y + 15, fill_width, 5, gauge_color
                    )

    def _draw_speed_slider(self, x: int, y: int, width: int) -> None:
        """Contrôle glissant du délai entre deux tours (0.1 à 3 secondes)."""
        minimum, maximum = 0.1, 3.0
        mouse = pr.get_mouse_position()
        mouse_over = x <= mouse.x <= x + width and y - 12 <= mouse.y <= y + 18
        if pr.is_mouse_button_pressed(pr.MOUSE_BUTTON_LEFT) and mouse_over:
            self._speed_slider_dragging = True
        if not pr.is_mouse_button_down(pr.MOUSE_BUTTON_LEFT):
            self._speed_slider_dragging = False
        if self._speed_slider_dragging:
            ratio = max(0.0, min(1.0, (mouse.x - x) / width))
            self.step_interval = minimum + ratio * (maximum - minimum)
        ratio = (self.step_interval - minimum) / (maximum - minimum)
        pr.draw_rectangle(x, y, width, 5, [45, 60, 80, 255])
        pr.draw_rectangle(x, y, int(width * ratio), 5, COLOR_CYAN)
        pr.draw_circle(int(x + width * ratio), y + 2, 8, COLOR_WHITE)

'''
    # If an earlier patch already added _advance_simulation, update its body
    # rather than defining the same method twice.
    advance_method = '''    def _advance_simulation(self) -> None:\n        """Avance d'un tour via l'API publique du moteur."""\n        if self.simulator is None or self.simulator.deadlocked:\n            self.simulation_running = False\n            return\n        self.last_moves = self.simulator.step()\n        if self.simulator.deadlocked:\n            self.simulation_running = False\n\n'''
    if "def _advance_simulation(self) -> None:" in source:
        previous_method = '''    def _advance_simulation(self) -> None:\n        """Avance d'un tour via l'API commune du moteur."""\n        if self.simulator is None or self.simulator.deadlocked:\n            self.simulation_running = False\n            return\n        self.simulator.step()\n        if self.simulator.deadlocked:\n            self.simulation_running = False\n            if self.simulator.error:\n                print(f"Simulation arrêtée : {self.simulator.error}")\n'''
        if previous_method in source:
            source = replace_once(
                source, previous_method, advance_method, "mise à jour step déjà présent"
            )
        helpers = helpers.replace(advance_method, "")

    source = insert_after(source, helpers_anchor, helpers, "helpers visuels et commandes")

    # Menu: make the existing capacity toggle control both the list and node gauges.
    cap_line = '''        if self._draw_button((60, 130, 450, 45), f"INFOS CAPACITÉ (--capacity-info) : {cap_status}"):\n            self.show_capacity_info = not self.show_capacity_info\n'''
    cap_line_new = '''        if self._draw_button((60, 130, 450, 45), f"INFOS CAPACITÉ : {cap_status}"):\n            self.show_capacity_info = not self.show_capacity_info\n            self.show_capacity_gauges = self.show_capacity_info\n'''
    source = replace_once(source, cap_line, cap_line_new, "toggle capacité")

    slider_old = '''        speed_label = f"VITESSE PAS A PAS : {self.step_interval:.1f}s"\n        pr.draw_text(speed_label, 60, 260, 20, COLOR_WHITE)\n        if self._draw_button((60, 290, 100, 35), "- 0.2s"):\n            self.step_interval = max(0.1, self.step_interval - 0.2)\n        if self._draw_button((170, 290, 100, 35), "+ 0.2s"):\n            self.step_interval = min(3.0, self.step_interval + 0.2)\n'''
    slider_new = '''        speed_label = f"VITESSE DE SIMULATION : {self.step_interval:.2f}s / tour"\n        pr.draw_text(speed_label, 60, 260, 20, COLOR_WHITE)\n        self._draw_speed_slider(60, 302, 320)\n        pr.draw_text("L : noms | K : jauges | T : traînées", 60, 340, 16, COLOR_GRAY)\n        pr.draw_text(\n            "F : suivre drone | R : caméra | RETOUR : annuler un tour",\n            60, 365, 16, COLOR_GRAY\n        )\n'''
    source = replace_once(source, slider_old, slider_new, "curseur de vitesse")

    # Keyboard view changes become interpolated; right click controls the orbit camera.
    source = replace_once(
        source,
        "                if pr.is_key_pressed(pr.KEY_UP):\n                    self.cam_yaw, self.cam_pitch = 0.0, 1.55\n                elif pr.is_key_pressed(pr.KEY_DOWN):\n                    self.cam_yaw, self.cam_pitch = 0.0, 0.05\n                elif pr.is_key_pressed(pr.KEY_LEFT):\n                    self.cam_yaw, self.cam_pitch = -math.pi / 2, 0.1\n                elif pr.is_key_pressed(pr.KEY_RIGHT):\n                    self.cam_yaw, self.cam_pitch = math.pi / 2, 0.1\n\n                if pr.is_mouse_button_down(pr.MOUSE_BUTTON_MIDDLE):\n                    delta = pr.get_mouse_delta()\n                    self.cam_yaw -= delta.x * 0.006\n                    self.cam_pitch = max(-1.55, min(1.55, self.cam_pitch + delta.y * 0.006))\n",
        "                if pr.is_key_pressed(pr.KEY_UP):\n                    self._set_camera_view(0.0, 1.55)\n                elif pr.is_key_pressed(pr.KEY_DOWN):\n                    self._set_camera_view(0.0, 0.05)\n                elif pr.is_key_pressed(pr.KEY_LEFT):\n                    self._set_camera_view(-math.pi / 2, 0.1)\n                elif pr.is_key_pressed(pr.KEY_RIGHT):\n                    self._set_camera_view(math.pi / 2, 0.1)\n\n                if self._camera_transition is not None:\n                    start_yaw, start_pitch, end_yaw, end_pitch, started = self._camera_transition\n                    progress = min(1.0, max(0.0, (current_time - started) / 0.4))\n                    eased = progress * progress * (3.0 - 2.0 * progress)\n                    self.cam_yaw = start_yaw + (end_yaw - start_yaw) * eased\n                    self.cam_pitch = start_pitch + (end_pitch - start_pitch) * eased\n                    if progress >= 1.0:\n                        self._camera_transition = None\n\n                if pr.is_mouse_button_down(pr.MOUSE_BUTTON_RIGHT):\n                    self._camera_transition = None\n                    delta = pr.get_mouse_delta()\n                    self.cam_yaw -= delta.x * 0.006\n                    self.cam_pitch = max(-1.55, min(1.55, self.cam_pitch + delta.y * 0.006))\n",
        "rotation souris droite et transitions caméra",
    )

    controls_anchor = '''                if pr.is_key_pressed(pr.KEY_SPACE):\n                    self.simulation_running = not self.simulation_running\n'''
    controls_replacement = controls_anchor + '''\n                if pr.is_key_pressed(pr.KEY_R):\n                    self._reset_camera()\n                if pr.is_key_pressed(pr.KEY_F):\n                    self._cycle_follow_drone()\n                if pr.is_key_pressed(pr.KEY_L):\n                    self.show_zone_labels = not self.show_zone_labels\n                if pr.is_key_pressed(pr.KEY_K):\n                    self.show_capacity_gauges = not self.show_capacity_gauges\n                if pr.is_key_pressed(pr.KEY_T):\n                    self.show_trails = not self.show_trails\n                if pr.is_key_pressed(pr.KEY_BACKSPACE) and self.simulator:\n                    self._undo_simulation()\n                    self.last_step_time = current_time\n'''
    source = replace_once(source, controls_anchor, controls_replacement, "raccourcis visuels et retour arrière")

    # Migrate both manual and automatic stepping to the single public API.
    old_manual = '''                if (pr.is_key_pressed(pr.KEY_N) or pr.is_key_pressed(pr.KEY_ENTER)) and not all_done and self.simulator:\n                    self.simulator.turn += 1\n                    self.simulator._simulate_turn()\n'''
    new_manual = '''                if (
                    pr.is_key_pressed(pr.KEY_N) or pr.is_key_pressed(pr.KEY_ENTER)
                ) and not all_done and self.simulator:
                    self._advance_simulation()
                    self.last_step_time = current_time
'''
    if old_manual in source:
        source = replace_once(source, old_manual, new_manual, "pas-à-pas public")
    old_auto = '''                if self.simulation_running and not all_done and self.simulator:\n                    if current_time - self.last_step_time > self.step_interval:\n                        self.simulator.turn += 1\n                        self.simulator._simulate_turn()\n                        self.last_step_time = current_time\n'''
    new_auto = '''                if self.simulation_running and not all_done and self.simulator:\n                    if current_time - self.last_step_time > self.step_interval:\n                        self._advance_simulation()\n                        self.last_step_time = current_time\n'''
    if old_auto in source:
        source = replace_once(source, old_auto, new_auto, "avance automatique publique")
    if "self.simulator._simulate_turn()" in source:
        # Old source can have whitespace changes; fail safely rather than leaving split turn logic.
        raise ValueError("Il reste un appel direct à _simulate_turn(); vérifiez le diff manuellement.")

    # Smooth camera around origin, or look at the selected drone.
    camera_old = '''            cam_x = self.cam_distance * math.cos(self.cam_pitch) * math.sin(self.cam_yaw)\n            cam_y = self.cam_distance * math.sin(self.cam_pitch)\n            cam_z = self.cam_distance * math.cos(self.cam_pitch) * math.cos(self.cam_yaw)\n            camera.position = [cam_x, cam_y, cam_z]\n'''
    camera_new = '''            focus = [0.0, 0.0, 0.0]\n            if self.follow_drone_id in self.drone_positions:\n                focused_position = self.drone_positions[self.follow_drone_id]\n                focus = list(focused_position)\n            cam_x = self.cam_distance * math.cos(self.cam_pitch) * math.sin(self.cam_yaw)\n            cam_y = self.cam_distance * math.sin(self.cam_pitch)\n            cam_z = self.cam_distance * math.cos(self.cam_pitch) * math.cos(self.cam_yaw)\n            camera.target = focus\n            camera.position = [focus[0] + cam_x, focus[1] + cam_y, focus[2] + cam_z]\n            self.hovered_zone = self._pick_hovered_zone(camera)\n'''
    source = replace_once(source, camera_old, camera_new, "cible caméra et survol")

    # Reduce animated background GPU work to every other displayed frame.
    bg_old = '''            if bg_anim:\n                bg_anim.render()\n'''
    bg_new = '''            if bg_anim:\n                # Le fond est recalculé une image sur deux; la RenderTexture\n                # conserve l'image précédente entre deux mises à jour.\n                if self.render_frame_index % 2 == 0:\n                    bg_anim.render()\n                self.render_frame_index += 1\n'''
    source = replace_once(source, bg_old, bg_new, "fond animé à demi-fréquence")

    # Color connection by queued demand vs capacity rather than a static colour.
    links_old = '''            if self.show_connections and self.graph:\n                for conn in self.graph.connections_list:\n                    p1 = self.node_positions.get(conn.zone1)\n                    p2 = self.node_positions.get(conn.zone2)\n                    if p1 and p2:\n                        pr.draw_line_3d(p1, p2, line_color)\n'''
    links_new = '''            if self.show_connections and self.graph:\n                for conn in self.graph.connections_list:\n                    p1 = self.node_positions.get(conn.zone1)\n                    p2 = self.node_positions.get(conn.zone2)\n                    if p1 and p2:\n                        waiting = self._pending_link_load(conn.zone1, conn.zone2)\n                        capacity = max(1, conn.max_link_capacity)\n                        line_color = self._connection_color(waiting / capacity)\n                        pr.draw_line_3d(p1, p2, line_color)\n'''
    source = replace_once(source, links_old, links_new, "charge visuelle des liaisons")

    # Use optional low-poly model on large maps. No asset is required for fallback.
    source = replace_once(
        source,
        "        planet_model = self._load_planet_model()\n",
        "        use_low_detail = bool(self.graph and len(self.graph.zones) >= 24)\n"
        "        planet_model = self._load_planet_model(low_detail=use_low_detail)\n",
        "sélection LOD sur grande carte",
    )

    planet_draw_anchor = '''                    else:\n                        pr.draw_billboard(camera, planet_texture, pos, size, tint)\n'''
    ring_draw = '''\n                    if self.simulator and zone_name == self.simulator.start_hub:\n                        self._draw_hub_ring(pos, size * 0.78, [80, 190, 255, 255])\n                    elif self.simulator and zone_name == self.simulator.end_hub:\n                        self._draw_hub_ring(pos, size * 0.78, [255, 90, 115, 255])\n'''
    source = insert_after(source, planet_draw_anchor, ring_draw, "anneaux colorés des hubs")

    # Draw trails before current drone models/spheres.
    drones_draw_anchor = '''                for drone in self.simulator.drones:\n                    d_pos = self.drone_positions[drone.id]\n'''
    trails_draw = '''                if self.show_trails:\n                    for trail in self.drone_trails.values():\n                        for trail_index in range(1, len(trail)):\n                            alpha = max(35, min(180, 35 + trail_index * 9))\n                            pr.draw_line_3d(\n                                trail[trail_index - 1], trail[trail_index],\n                                [50, 190, 255, alpha]\n                            )\n\n'''
    source = replace_once(source, drones_draw_anchor, trails_draw + drones_draw_anchor, "traînées de drones")

    # Track trails after interpolation of each drone's displayed position.
    drone_move_old = '''                        curr[0] += (target_pos[0] - curr[0]) * 0.12\n                        curr[1] += ((target_pos[1] + self.planet_size * 0.5) - curr[1]) * 0.12\n                        curr[2] += (target_pos[2] - curr[2]) * 0.12\n'''
    drone_move_new = drone_move_old + '''                        if self.show_trails:\n                            self._track_drone_trail(drone.id, curr)\n'''
    source = replace_once(source, drone_move_old, drone_move_new, "collecte des traînées")

    # Add node labels/gauges after the 3D scene is finished.
    end_3d_anchor = '''            pr.end_mode_3d()\n\n            if self.simulator:\n'''
    end_3d_replacement = '''            pr.end_mode_3d()\n\n            self._draw_zone_overlays(camera)\n\n            if self.simulator:\n'''
    source = replace_once(source, end_3d_anchor, end_3d_replacement, "noms et jauges HUD")

    # A compact always-on statistics area.
    turn_line = '''                pr.draw_text(f"Tour : {self.simulator.turn}", 20, 45, 22, COLOR_WHITE)\n'''
    stats = '''                delivered_count = sum(
                    1 for drone in self.simulator.drones
                    if drone.status == "delivered"
                )
                drone_count = len(self.simulator.drones)
                throughput = delivered_count / max(1, self.simulator.turn)
                stats_x = self.width - 270
                pr.draw_text(
                    f"Tours écoulés : {self.simulator.turn}",
                    stats_x, 20, 16, COLOR_WHITE
                )
                pr.draw_text(
                    f"Drones arrivés : {delivered_count}/{drone_count}",
                    stats_x, 42, 16, COLOR_WHITE
                )
                pr.draw_text(
                    f"Débit moyen : {throughput:.2f} drone/tour",
                    stats_x, 64, 15, COLOR_CYAN
                )
                if self.follow_drone_id:
                    pr.draw_text(
                        f"Suivi : {self.follow_drone_id} (F suivant)",
                        stats_x, 85, 14, COLOR_YELLOW
                    )
'''
    source = insert_after(source, turn_line, stats, "statistiques de simulation")

    # Refresh the help line and keep an explicit deadlock indicator.
    help_old = '''                pr.draw_text("ESPACE : Pause | N / ENTRÉE : Pas à Pas | P : Menu", 20, 75, 15, COLOR_GRAY)\n'''
    help_new = '''                pr.draw_text(
                    "ESPACE : lecture/pause | N/ENTRÉE : tour | RETOUR : annuler | P : menu",
                    20, 75, 14, COLOR_GRAY
                )
                pr.draw_text(
                    "Clic droit : tourner | Molette : zoom | Flèches : vue | "
                    "F : suivre drone | R : reset",
                    20, 94, 13, COLOR_GRAY
                )
                pr.draw_text(
                    "L : noms | K : jauges | T : traînées",
                    20, 112, 13, COLOR_GRAY
                )
'''
    source = replace_once(source, help_old, help_new, "aide clavier")
    if "                    y_cap = 100\n" in source:
        source = replace_once(
            source, "                    y_cap = 100\n",
            "                    y_cap = 140\n", "placement panneau capacité"
        )

    # Deadlock display precedes success display and does not mask an error.
    success_old = '''                if all_done:\n                    pr.draw_text("TOUS LES DRONES SONT ARRIVÉS !", 20, self.height - 50, 22, [50, 220, 100, 255])\n'''
    success_new = '''                if self.simulator.deadlocked:\n                    message = self.simulator.error or "Aucun mouvement possible."\n                    pr.draw_text(\n                        "SIMULATION BLOQUÉE", 20, self.height - 50, 22, [255, 80, 80, 255]\n                    )\n                    pr.draw_text(\n                        message[:100], 20, self.height - 25, 14, [255, 135, 135, 255]\n                    )\n                elif all_done:\n                    pr.draw_text(\n                        "TOUS LES DRONES SONT ARRIVÉS !",\n                        20, self.height - 50, 22, [50, 220, 100, 255]\n                    )\n'''
    if success_old in source:
        source = replace_once(source, success_old, success_new, "affichage deadlock")
    elif "if self.simulator.deadlocked:" not in source:
        raise ValueError("Bloc de fin de simulation introuvable.")

    return source


def update_file(path: Path, patcher: Callable[[str], str]) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = patcher(original)
    if updated == original:
        print(f"OK : {path.relative_to(ROOT)} déjà à jour")
        return False
    backup = path.with_suffix(path.suffix + ".visual-upgrade.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(updated, encoding="utf-8")
    print(f"OK : {path.relative_to(ROOT)} modifié (sauvegarde : {backup.name})")
    return True


def main() -> int:
    if not VIEWER.is_file() or not SIMULATOR.is_file():
        print("Erreur : lancez ce script depuis la racine du dépôt Drone_controle.", file=sys.stderr)
        return 2
    try:
        # Préflight les deux patchs avant toute écriture pour éviter un dépôt à
        # moitié modifié si une ancre ne correspond pas à la version installée.
        original_sim = SIMULATOR.read_text(encoding="utf-8")
        original_view = VIEWER.read_text(encoding="utf-8")
        updated_sim = patch_simulator(original_sim)
        updated_view = patch_viewer(original_view)
        for path, original, updated in (
            (SIMULATOR, original_sim, updated_sim),
            (VIEWER, original_view, updated_view),
        ):
            if updated == original:
                print(f"OK : {path.relative_to(ROOT)} déjà à jour")
                continue
            backup = path.with_suffix(path.suffix + ".visual-upgrade.bak")
            if not backup.exists():
                shutil.copy2(path, backup)
            path.write_text(updated, encoding="utf-8")
            print(f"OK : {path.relative_to(ROOT)} modifié (sauvegarde : {backup.name})")
    except (OSError, ValueError) as error:
        print(f"Erreur : {error}. Aucun patch n'a été écrit.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
