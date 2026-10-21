import glob
import math
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import pyray as pr
from pyray import KeyboardKey, MouseButton, TextureFilter

from graph import NetworkGraph
from simulation import Simulator
from intro_video import IntroVideo
from parser import parse_map_file
from planet_shader import ATMOSPHERES, PlanetShader


# États de l'interface
STATE_SIMULATION = 0
STATE_MENU_MAIN = 1
STATE_MENU_MAPS = 2
STATE_MENU_OPTIONS = 3

# Définition de couleurs RGBA personnalisées (100% compatibles PyRay)
COLOR_CYAN = [0, 200, 255, 255]
COLOR_GOLD = [255, 203, 0, 255]
COLOR_YELLOW = [255, 249, 0, 255]
COLOR_GRAY = [255, 130, 130, 255]
COLOR_WHITE = [245, 245, 245, 255]

# Rayon réel des planètes générées par make_planet_glb.py.
PLANET_MODEL_NATIVE_RADIUS = 2.0
# Sert à ajuster l'échelle du modèle. Avec 2.0 le diamètre affiché vaut
# planet_size ; avec 4 (valeur actuelle) les planètes sont deux fois plus
# petites.
PLANET_MODEL_RADIUS = 4

# À partir de ce nombre de zones : planet_low.glb pour les zones non-hubs.
LOW_DETAIL_ZONE_COUNT = 14

# Fond animé (assets/abstract.glb) : caméra alignée sur l'aperçu du script Blender.
# Conversion Blender (x, y, z) -> raylib (x, z, -y).
BG_CAMERA_POS = [0.0, 13.0, 8.0]
BG_CAMERA_TARGET = [0.0, 0.0, -1.0]
BG_CAMERA_FOVY = 50.0
BG_CLEAR_COLOR = [2, 2, 8, 255]
BG_RENDER_SCALE = 1.0   # 1.5 ou 2.0 = bords plus lisses (rendu plus lourd)
# Le fond n'est rendu qu'une image sur deux : on avance de 2 images
# d'animation à chaque rendu pour garder la vitesse d'origine.
BG_ANIM_SPEED = 2.0


class AnimatedBackground:
    """Fond 3D animé (animation squelettique d'un GLB), rendu dans une RenderTexture
    avec sa propre caméra, puis affiché en plein écran derrière la scène principale."""

    def __init__(self, path: str, width: int, height: int) -> None:
        """Charge le GLB et crée la texture de rendu."""
        self.model = pr.load_model(path)
        self.anim_count = pr.ffi.new("int *")
        self.animations = pr.load_model_animations(path, self.anim_count)
        self.frame = 0.0
        self.target = pr.load_render_texture(
            int(width * BG_RENDER_SCALE), int(height * BG_RENDER_SCALE)
        )
        pr.set_texture_filter(self.target.texture, TextureFilter.TEXTURE_FILTER_BILINEAR)
        self.camera = pr.Camera3D(
            BG_CAMERA_POS, BG_CAMERA_TARGET, [0.0, 1.0, 0.0], BG_CAMERA_FOVY, 0
        )

    def _frame_count(self) -> int:
        """Nombre d'images de la première animation (0 s'il n'y en a pas)."""
        if not self.animations or self.anim_count[0] <= 0:
            return 0
        anim = self.animations[0]
        for attr in ("keyframeCount", "frameCount"):   # nom selon la version de raylib
            try:
                return max(1, int(getattr(anim, attr)))
            except AttributeError:
                continue
        return 1

    def render(self) -> None:
        """À appeler avant begin_drawing() : avance l'animation et dessine dans la RenderTexture."""
        count = self._frame_count()
        if count:
            self.frame = (self.frame + BG_ANIM_SPEED) % count
            pr.update_model_animation(self.model, self.animations[0], int(self.frame))

        pr.begin_texture_mode(self.target)
        pr.clear_background(BG_CLEAR_COLOR)
        pr.begin_mode_3d(self.camera)
        pr.draw_model(self.model, [0.0, 0.0, 0.0], 1.0, pr.WHITE)
        pr.end_mode_3d()
        pr.end_texture_mode()

    def draw(self, darken: int = 110) -> None:
        """Affiche la texture en plein écran, légèrement assombrie."""
        sw, sh = pr.get_screen_width(), pr.get_screen_height()
        tex = self.target.texture
        src = pr.Rectangle(0, 0, tex.width, -tex.height)   # RenderTexture inversée en Y
        dst = pr.Rectangle(0, 0, sw, sh)
        pr.draw_texture_pro(tex, src, dst, pr.Vector2(0, 0), 0.0, pr.WHITE)
        pr.draw_rectangle(0, 0, sw, sh, [0, 0, 0, darken])

    def unload(self) -> None:
        """Libère le modèle, les animations et la texture."""
        if self.animations and self.anim_count[0] > 0:
            pr.unload_model_animations(self.animations, self.anim_count[0])
        pr.unload_model(self.model)
        pr.unload_render_texture(self.target)


class Visualizer3D:
    """Représentation graphique 3D de la simulation (raylib)."""

    def __init__(
        self,
        graph: Optional[NetworkGraph] = None,
        simulator: Optional[Simulator] = None,
        map_path: str = "maps/easy/linear.txt"
    ) -> None:
        """Prépare le visualiseur ; la fenêtre s'ouvre dans run()."""
        self.width = 1200
        self.height = 800

        self.node_positions: Dict[str, List[float]] = {}
        self.drone_positions: Dict[str, List[float]] = {}

        # Options de simulation / affichage
        self.show_capacity_info = False  # Flag --capacity-info
        self.step_interval = 0.8         # Vitesse de simulation
        self.show_connections = True

        # "custom" = procedural rings/height levels; "map" = map x/y.
        self.layout_mode = "custom"
        self.show_minimap = True  # Radar 2D (touche M)
        self._minimap_signature: Optional[Tuple[Tuple[str, int, int], ...]] = None
        self._minimap_drone_positions: Dict[str, List[float]] = {}

        # Affichage interactif et diagnostic de la scène.
        self.show_zone_labels = False
        self.show_capacity_gauges = False
        self.show_trails = True
        self.follow_drone_id: Optional[str] = None
        self.hovered_zone: Optional[str] = None
        self.drone_trails: Dict[str, List[List[float]]] = {}
        self.render_frame_index = 0
        self.last_moves: List[str] = []
        self._speed_slider_dragging = False
        self._camera_transition: Optional[Tuple[float, float, float, float, float]] = None

        # Contrôle de la caméra sphérique (Attributs d'instance)
        self.cam_distance = 35.0
        self.cam_yaw = 0.0
        self.cam_pitch = 0.95
        self._home_cam_distance = 35.0

        # État initial
        self.app_state = STATE_SIMULATION if graph else STATE_MENU_MAIN
        self.simulation_running = False
        self.last_step_time = time.time()

        # Scan du dossier maps/ pour le menu
        self.categorized_maps: Dict[str, List[str]] = self._scan_maps_directory("maps")
        self.current_category = "easy" if "easy" in self.categorized_maps else "other"

        self.graph = graph
        self.simulator = simulator
        self.current_map_path = map_path

        if self.graph and self.simulator:
            self._setup_layout()
        else:
            self._load_map(self.current_map_path)

    def _setup_layout(self) -> None:
        """Calcule les dimensions dynamiques, réinitialise la caméra et les drones."""
        if not self.graph or not self.simulator:
            return

        self.num_nodes = max(1, len(self.graph.zones))
        self.radius_x = max(10.0, min(35.0, math.sqrt(self.num_nodes) * 4.5))
        self.radius_z = max(6.0, min(22.0, math.sqrt(self.num_nodes) * 3.0))

        self.planet_size = max(1.2, min(4.2, 28.0 / math.sqrt(self.num_nodes)))
        self.drone_scale = max(0.04, min(0.14, 0.8 / math.sqrt(self.num_nodes)))

        # Réinitialisation de la caméra adaptative
        # Keep the added upper/lower tiers inside the initial camera frame.
        _height_step_for_view = max(3.2, self.planet_size * 1.7)
        _map_width_for_view = (
            self.radius_x * 2.3 if self.layout_mode == "map" else 0.0
        )
        self.cam_distance = max(
            35.0,
            self.radius_z * 2.2,
            _map_width_for_view,
            _height_step_for_view * 5.0,
        )
        self.cam_yaw = 0.0
        self.cam_pitch = 0.95
        self._home_cam_distance = self.cam_distance
        self.follow_drone_id = None
        self._camera_transition = None
        self.drone_trails.clear()
        self.show_trails = self.num_nodes < 24
        self.last_moves = []

        self.node_positions.clear()
        self.drone_positions.clear()

        self._compute_3d_layout()
        self._init_drones()

    def _scan_maps_directory(self, maps_dir: str) -> Dict[str, List[str]]:
        """Scanne le dossier maps/ et catégorise les fichiers par sous-dossiers."""
        categories: Dict[str, List[str]] = {"easy": [], "medium": [], "hard": [], "challenger": [], "other": []}

        if not os.path.exists(maps_dir):
            return categories

        for root, _, files in os.walk(maps_dir):
            for file in sorted(files):
                if file.endswith(".txt"):
                    full_path = os.path.join(root, file)
                    folder_name = os.path.basename(root).lower()

                    if folder_name in categories:
                        categories[folder_name].append(full_path)
                    else:
                        categories["other"].append(full_path)

        return categories

    def _load_map(self, file_path: str) -> bool:
        """Parse une nouvelle carte et réinitialise le jeu immédiatement."""
        try:
            # Rechargement propre du graphe et du simulateur
            self.graph, self.simulator = parse_map_file(file_path)
            self.current_map_path = file_path
            self.simulation_running = False

            # Recalcul de la scène 3D, de la caméra et des positions
            self._setup_layout()
            return True
        except Exception as e:
            print(f"⚠ Erreur lors du chargement de la carte {file_path} : {e}")
            return False

    def _compute_3d_layout(self) -> None:
        """Répartit les planètes sur plusieurs anneaux concentriques."""
        if not self.graph or not self.simulator:
            return

        if self.layout_mode == "map":
            self._compute_map_layout()
            return

        zones = list(self.graph.zones.keys())
        start_x = self.radius_x * 1.3

        self.node_positions[self.simulator.start_hub] = [-start_x, 0.0, 0.0]
        self.node_positions[self.simulator.end_hub] = [start_x, 0.0, 0.0]

        internal_zones = [
            z for z in zones
            if z not in (self.simulator.start_hub, self.simulator.end_hub)
        ]

        n = len(internal_zones)
        if n == 0:
            return

        num_rings = 7 if n >= 12 else (2 if n >= 6 else 1)

        # VISUAL DEPTH UPGRADE: stable height layers based on map topology.
        # Higher-degree zones tend to stay near the central level; others use
        # repeatable positive/negative levels instead of tiny random-looking offsets.
        _max_degree = max(
            (len(self.graph.get_neighbors(name)) for name in internal_zones),
            default=0,
        )
        _central_degree_threshold = max(3, _max_degree - 1)
        _height_step = max(3.2, self.planet_size * 1.7)
        _height_pattern = (0, -1, 1, -2, 2)

        for i, zone_name in enumerate(internal_zones):
            ring_idx = i % num_rings
            radius_x = (self.radius_x * 0.25) + ring_idx * (self.radius_x * 0.25)
            radius_z = (self.radius_z * 0.25) + ring_idx * (self.radius_z * 0.25)

            items_per_ring = max(1, n // num_rings)
            ring_pos = i // num_rings

            angle = ((2 * math.pi * ring_pos / items_per_ring) + (ring_idx * 0.9))

            x = radius_x * math.cos(angle)
            z = radius_z * math.sin(angle)
            # Keep highly connected zones around y=0. Other zones are spread
            # above and below the ring in a deterministic, balanced pattern.
            _degree = len(self.graph.get_neighbors(zone_name))
            if _degree >= _central_degree_threshold:
                _height_level = 0
            else:
                _pattern_index = (i + ring_idx) % len(_height_pattern)
                _height_level = _height_pattern[_pattern_index]
            y = _height_level * _height_step

            self.node_positions[zone_name] = [x, y, z]

    def _compute_map_layout(self) -> None:
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
        fallback = self._drone_anchor(self.simulator.start_hub) or [0.0, 0.0, 0.0]
        for drone in self.simulator.drones:
            self.drone_positions[drone.id] = list(
                self._drone_anchor(drone.current_location) or fallback
            )

    def _planet_render_radius(self, is_hub: bool) -> float:
        """Rayon réellement affiché d'une planète (dépend de PLANET_MODEL_RADIUS)."""
        size = self.planet_size * (1.4 if is_hub else 1.0)
        return size * PLANET_MODEL_NATIVE_RADIUS / (2.0 * PLANET_MODEL_RADIUS)

    def _drone_anchor(self, location: str) -> Optional[List[float]]:
        """Position d'un drone : sur la zone, ou au milieu du lien « a-b ».

        Un drone en vol vers une zone restreinte a pour emplacement le nom de
        la connexion (« zoneA-zoneB ») : il est dessiné au milieu du lien.
        """
        if self.simulator is None:
            return None
        position = self.node_positions.get(location)
        if position is not None:
            is_hub = location in (self.simulator.start_hub, self.simulator.end_hub)
            lift = self._planet_render_radius(is_hub) + self.planet_size * 0.05
            return [position[0], position[1] + lift, position[2]]
        first, _, second = location.partition("-")
        start = self.node_positions.get(first)
        end = self.node_positions.get(second)
        if start is not None and end is not None:
            return [
                (start[0] + end[0]) / 2,
                (start[1] + end[1]) / 2 + self.planet_size * 0.4,
                (start[2] + end[2]) / 2,
            ]
        return None

    def _init_drones(self) -> None:
        """Place tous les drones sur la zone de départ."""
        if not self.simulator:
            return
        start = self._drone_anchor(self.simulator.start_hub) or [0.0, 0.0, 0.0]
        for drone in self.simulator.drones:
            self.drone_positions[drone.id] = list(start)

    def _restart_simulation(self) -> None:
        """Recharge la carte courante."""
        if self.current_map_path:
            self._load_map(self.current_map_path)

    def _all_drones_delivered(self) -> bool:
        """True quand chaque drone est sur la zone d'arrivée."""
        if not self.simulator:
            return True
        for drone in self.simulator.drones:
            if drone.current_location != self.simulator.end_hub:
                return False
        return True

    def _planet_atmosphere_for_zone(
        self, zone_name: str, index: int
    ) -> Tuple[float, float, float]:
        """Use explicit map color for the rim, otherwise cycle subtle palettes."""
        zone = self.graph.get_zone(zone_name) if self.graph is not None else None
        if zone is not None and zone.color:
            raw = zone.color.strip().lower()
            named = {
                "red": (1.00, 0.20, 0.22),
                "green": (0.24, 0.92, 0.50),
                "blue": (0.25, 0.52, 1.00),
                "cyan": (0.12, 0.85, 1.00),
                "yellow": (1.00, 0.78, 0.18),
                "orange": (1.00, 0.40, 0.12),
                "purple": (0.62, 0.30, 1.00),
                "magenta": (1.00, 0.20, 0.72),
                "pink": (1.00, 0.42, 0.68),
                "white": (0.82, 0.90, 1.00),
                "black": (0.28, 0.38, 0.52),
                "gray": (0.48, 0.60, 0.72),
                "grey": (0.48, 0.60, 0.72),
            }
            if raw in named:
                return named[raw]
            if raw.startswith("#") and len(raw) == 7:
                try:
                    return tuple(
                        int(raw[offset:offset + 2], 16) / 255.0
                        for offset in (1, 3, 5)
                    )  # type: ignore[return-value]
                except ValueError:
                    pass
        return ATMOSPHERES[index % len(ATMOSPHERES)]

    def _load_planet_model(self, low_detail: bool = False) -> Any:
        """Charge un modèle; les grandes cartes peuvent utiliser planet_low.glb."""
        normal_path = os.path.join("assets", "planet_0.glb")
        low_path = os.path.join("assets", "planet_3.glb")
        path = low_path if low_detail and os.path.exists(low_path) else normal_path
        if os.path.exists(path):
            try:
                return pr.load_model(path)
            except Exception as e:
                print(f"⚠ Erreur modèle planète ({path}) : {e}")
        return None

    @staticmethod
    def _edge_key(zone1: str, zone2: str) -> Tuple[str, str]:
        """Clé d'une liaison, indépendante du sens."""
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
        # Chemin le plus court : pas de tour complet inutile.
        shortest = (yaw - self.cam_yaw + math.pi) % (2.0 * math.pi) - math.pi
        self._camera_transition = (
            self.cam_yaw, self.cam_pitch, self.cam_yaw + shortest, pitch, time.time()
        )

    def _reset_camera(self) -> None:
        """Retour à la vue par défaut (distance d'origine, plus de suivi)."""
        self.follow_drone_id = None
        self._set_camera_view(0.0, 0.95)
        self.cam_distance = self._home_cam_distance

    def _cycle_follow_drone(self) -> None:
        """Passe au drone suivant pour la caméra de suivi."""
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
            anchor = self._drone_anchor(drone.current_location)
            if anchor is not None:
                self.drone_positions[drone.id] = anchor

    def _track_drone_trail(self, drone_id: str, position: List[float]) -> None:
        """Ajoute la position à la traînée du drone (18 points au plus)."""
        trail = self.drone_trails.setdefault(drone_id, [])
        if not trail or sum(
            (position[axis] - trail[-1][axis]) ** 2 for axis in range(3)
        ) >= 0.0064:
            trail.append(list(position))
        if len(trail) > 18:
            del trail[:-18]

    def _pick_hovered_zone(self, camera: Any) -> Optional[str]:
        """Zone la plus proche du curseur (dans un rayon en pixels), ou None."""
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

    def _minimap_zone_color(self, zone_name: str) -> List[int]:
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
        """Dessine un radar 2D basé sur les coordonnées x/y du fichier de carte.

        La disposition en anneaux utilisée par la scène 3D n'est jamais utilisée
        ici : le mini-map reproduit la géométrie définie dans le fichier .txt.
        """
        if (
            not self.show_minimap
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
        if self._minimap_signature != signature:
            self._minimap_signature = signature
            self._minimap_drone_positions = {}

        drone_palette = [
            [40, 235, 255, 255], [255, 175, 65, 255],
            [225, 105, 255, 255], [130, 255, 135, 255],
            [255, 235, 90, 255], [255, 105, 145, 255],
            [115, 160, 255, 255], [255, 255, 255, 255],
        ]
        for index, drone in enumerate(self.simulator.drones):
            zone_point = map_points.get(drone.current_location)
            if zone_point is None and "-" in drone.current_location:
                # Drone en vol : milieu de la connexion « a-b ».
                first_name, _, second_name = drone.current_location.partition("-")
                if first_name in map_points and second_name in map_points:
                    zone_point = (
                        (map_points[first_name][0] + map_points[second_name][0]) / 2,
                        (map_points[first_name][1] + map_points[second_name][1]) / 2,
                    )
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
        if pr.is_mouse_button_pressed(MouseButton.MOUSE_BUTTON_LEFT) and mouse_over:
            self._speed_slider_dragging = True
        if not pr.is_mouse_button_down(MouseButton.MOUSE_BUTTON_LEFT):
            self._speed_slider_dragging = False
        if self._speed_slider_dragging:
            ratio = max(0.0, min(1.0, (mouse.x - x) / width))
            self.step_interval = minimum + ratio * (maximum - minimum)
        ratio = (self.step_interval - minimum) / (maximum - minimum)
        pr.draw_rectangle(x, y, width, 5, [45, 60, 80, 255])
        pr.draw_rectangle(x, y, int(width * ratio), 5, COLOR_CYAN)
        pr.draw_circle(int(x + width * ratio), y + 2, 8, COLOR_WHITE)

    def _load_planet_texture(self) -> Any:
        """Repli : ancienne planète 2D (billboard) si le GLB est introuvable."""
        path = os.path.join("assets", "planet.png")
        if os.path.exists(path):
            texture = pr.load_texture(path)
            pr.set_texture_filter(texture, TextureFilter.TEXTURE_FILTER_BILINEAR)
            return texture

        img = pr.gen_image_color(100, 100, pr.BLANK)
        pr.image_draw_circle(img, 50, 50, 45, pr.DARKBLUE)
        texture = pr.load_texture_from_image(img)
        pr.unload_image(img)
        return texture

    def _draw_background(self, texture: Any, darken: int = 110) -> None:
        """Fond statique abstract.jpg, recadré pour remplir l'écran."""
        sw, sh = pr.get_screen_width(), pr.get_screen_height()
        tw, th = texture.width, texture.height
        scale = max(sw / tw, sh / th)
        src_w, src_h = sw / scale, sh / scale

        src = pr.Rectangle((tw - src_w) / 2, (th - src_h) / 2, src_w, src_h)
        dst = pr.Rectangle(0, 0, sw, sh)

        pr.draw_texture_pro(texture, src, dst, pr.Vector2(0, 0), 0.0, pr.WHITE)
        pr.draw_rectangle(0, 0, sw, sh, [0, 0, 0, darken])

    def _draw_button(self, rect: Tuple[float, float, float, float], text: str) -> bool:
        """Dessine un bouton ; True à la frame où on clique dessus."""
        mouse_pos = pr.get_mouse_position()
        r = pr.Rectangle(rect[0], rect[1], rect[2], rect[3])
        is_hovered = pr.check_collision_point_rec(mouse_pos, r)

        bg_color = [40, 60, 90, 230] if is_hovered else [20, 30, 45, 200]
        border_color = [0, 200, 255, 255] if is_hovered else [60, 100, 140, 255]

        pr.draw_rectangle_rec(r, bg_color)
        pr.draw_rectangle_lines_ex(r, 2, border_color)

        text_size = pr.measure_text(text, 20)
        text_x = int(rect[0] + (rect[2] - text_size) / 2)
        text_y = int(rect[1] + (rect[3] - 20) / 2)

        text_color = COLOR_WHITE if is_hovered else COLOR_GRAY
        pr.draw_text(text, text_x, text_y, 20, text_color)

        return is_hovered and pr.is_mouse_button_pressed(MouseButton.MOUSE_BUTTON_LEFT)

    def _draw_main_menu(self) -> Optional[str]:
        """Menu principal / pause ; renvoie "EXIT" pour quitter."""
        pr.draw_rectangle(0, 0, self.width, self.height, [5, 10, 20, 210])

        title = "FLY-IN : MENU PRINCIPAL"
        pr.draw_text(title, int((self.width - pr.measure_text(title, 36)) / 2), 120, 36, COLOR_CYAN)

        btn_w, btn_h = 280, 50
        start_x = (self.width - btn_w) / 2
        start_y = 220

        if self._draw_button((start_x, start_y, btn_w, btn_h), "CONTINUER"):
            self.app_state = STATE_SIMULATION

        if self._draw_button((start_x, start_y + 70, btn_w, btn_h), "RECOMMENCER"):
            self._restart_simulation()
            self.app_state = STATE_SIMULATION

        if self._draw_button((start_x, start_y + 140, btn_w, btn_h), "CHOISIR UNE CARTE"):
            self.app_state = STATE_MENU_MAPS

        if self._draw_button((start_x, start_y + 210, btn_w, btn_h), "OPTIONS"):
            self.app_state = STATE_MENU_OPTIONS

        if self._draw_button((start_x, start_y + 280, btn_w, btn_h), "QUITTER"):
            return "EXIT"

        return None

    def _draw_maps_menu(self) -> None:
        """Choix de la carte, un onglet par difficulté."""
        pr.draw_rectangle(0, 0, self.width, self.height, [5, 10, 20, 230])
        pr.draw_text("SELECTION DE LA CARTE", 50, 40, 32, COLOR_CYAN)

        categories = ["easy", "medium", "hard", "challenger", "other"]
        tab_x = 50
        for cat in categories:
            rect = (tab_x, 90, 130, 35)   # 130 px : « CHALLENGER » débordait de 110
            if self._draw_button(rect, cat.upper()):
                self.current_category = cat
            tab_x += 140

        maps_list = self.categorized_maps.get(self.current_category, [])
        y_pos = 150

        if not maps_list:
            pr.draw_text("Aucune carte trouvée dans cette catégorie.", 60, y_pos, 20, COLOR_GRAY)

        for map_file in maps_list:
            file_name = os.path.basename(map_file)
            is_current = (map_file == self.current_map_path)
            display_name = f"► {file_name}" if is_current else file_name

            if self._draw_button((60, y_pos, 420, 42), display_name):
                # Chargement de la nouvelle carte & bascule directe vers la simulation
                if self._load_map(map_file):
                    self.app_state = STATE_SIMULATION

            y_pos += 50
            if y_pos > self.height - 100:
                break

        if self._draw_button((50, self.height - 70, 180, 45), "◄ RETOUR"):
            self.app_state = STATE_MENU_MAIN

    def _draw_options_menu(self) -> None:
        """Options d'affichage, disposition et vitesse de simulation."""
        pr.draw_rectangle(0, 0, self.width, self.height, [5, 10, 20, 230])
        pr.draw_text("OPTIONS DE VISUALISATION", 50, 40, 32, COLOR_CYAN)

        cap_status = "ACTIVÉ" if self.show_capacity_info else "DÉSACTIVÉ"
        if self._draw_button((60, 130, 450, 45), f"INFOS CAPACITÉ : {cap_status}"):
            self.show_capacity_info = not self.show_capacity_info
            self.show_capacity_gauges = self.show_capacity_info

        conn_status = "ACTIVÉ" if self.show_connections else "DÉSACTIVÉ"
        if self._draw_button((60, 190, 450, 45), f"AFFICHER CONNEXIONS : {conn_status}"):
            self.show_connections = not self.show_connections

        layout_label = (
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

        if self._draw_button((50, self.height - 70, 180, 45), "◄ RETOUR"):
            self.app_state = STATE_MENU_MAIN

    def run(self) -> None:
        """Ouvre la fenêtre et boucle jusqu'à la fermeture."""
        pr.init_window(self.width, self.height, "Fly-in : Visualisation 3D")
        pr.set_target_fps(60)

        # INTRO VIDÉO
        intro_path = os.path.join("assets", "intro.mp4")
        if os.path.exists(intro_path):
            try:
                intro = IntroVideo(intro_path)
                while not pr.window_should_close() and not intro.finished:
                    intro.update(pr.get_frame_time())
                    pr.begin_drawing()
                    pr.clear_background(pr.BLACK)
                    intro.draw()
                    pr.end_drawing()
                intro.close()
            except Exception as e:
                print(f"⚠ Erreur vidéo intro : {e}")

        # ASSETS 3D
        # Le modèle principal sert aux petites cartes et aux hubs.
        # Sur les grandes cartes, les autres planet*.glb sont répartis
        # aléatoirement entre les zones non-hubs.
        planet_model = self._load_planet_model()
        planet_models_low: List[Any] = []
        main_planet_path = os.path.normpath(
            os.path.join("assets", "planet_0.glb")
        )

        for model_path in sorted(
            glob.glob(os.path.join("assets", "planet*.glb"))
        ):
            # planet_0.glb reste le modèle principal ; ne pas le recharger.
            if os.path.normpath(model_path) == main_planet_path:
                continue
            try:
                loaded_model = pr.load_model(model_path)
                planet_models_low.append(loaded_model)
                print(f"Planète variante chargée : {model_path}")
            except Exception as error:
                print(
                    f"⚠ Impossible de charger la planète {model_path} : "
                    f"{error}"
                )

        planet_shader = (
            PlanetShader.create()
            if planet_model is not None or planet_models_low
            else None
        )
        if planet_shader is not None:
            try:
                if planet_model is not None:
                    planet_shader.apply(planet_model)
                for loaded_model in planet_models_low:
                    planet_shader.apply(loaded_model)
            except Exception as error:
                print(
                    "⚠ Shader de planète désactivé, "
                    f"rendu standard conservé : {error}"
                )
                try:
                    planet_shader.unload()
                except Exception:
                    pass
                planet_shader = None

        planet_texture = (
            None if planet_model is not None else self._load_planet_texture()
        )

        # Chaque zone garde la même variante pendant le rendu, plutôt que de
        # changer de planète à chaque image.
        low_planet_by_zone: Dict[str, Any] = {}

        # Fond : abstract.glb (animé) en priorité, sinon abstract.jpg (image fixe)
        bg_anim = None
        bg_glb_path = os.path.join("assets", "abstract.glb")
        if os.path.exists(bg_glb_path):
            try:
                bg_anim = AnimatedBackground(bg_glb_path, self.width, self.height)
            except Exception as e:
                print(f"⚠ Erreur fond animé : {e}")
                bg_anim = None

        bg_texture = None
        bg_path = os.path.join("assets", "abstract.jpg")
        if bg_anim is None and os.path.exists(bg_path):
            bg_texture = pr.load_texture(bg_path)
            pr.set_texture_filter(bg_texture, TextureFilter.TEXTURE_FILTER_BILINEAR)

        model_path = os.path.join("assets", "drone.glb")
        drone_model, animations = None, None
        anim_count = pr.ffi.new("int *")
        anim_frame_counter = 0.0

        if os.path.exists(model_path):
            try:
                drone_model = pr.load_model(model_path)
                animations = pr.load_model_animations(model_path, anim_count)
            except Exception as e:
                print(f"Erreur modèle 3D : {e}")

        bg_color = [2, 2, 8, 255]

        camera = pr.Camera3D([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 55.0, 0)

        while not pr.window_should_close():
            current_time = time.time()
            all_done = self._all_drones_delivered()

            # TOUCHE P : Ouvrir / Fermer le menu Pause
            if pr.is_key_pressed(KeyboardKey.KEY_P):
                if self.app_state == STATE_SIMULATION:
                    self.app_state = STATE_MENU_MAIN
                else:
                    self.app_state = STATE_SIMULATION

            if self.app_state == STATE_SIMULATION:
                if pr.is_key_pressed(KeyboardKey.KEY_UP):
                    self._set_camera_view(0.0, 1.55)
                elif pr.is_key_pressed(KeyboardKey.KEY_DOWN):
                    self._set_camera_view(0.0, 0.05)
                elif pr.is_key_pressed(KeyboardKey.KEY_LEFT):
                    self._set_camera_view(-math.pi / 2, 0.1)
                elif pr.is_key_pressed(KeyboardKey.KEY_RIGHT):
                    self._set_camera_view(math.pi / 2, 0.1)

                if self._camera_transition is not None:
                    start_yaw, start_pitch, end_yaw, end_pitch, started = self._camera_transition
                    progress = min(1.0, max(0.0, (current_time - started) / 0.4))
                    eased = progress * progress * (3.0 - 2.0 * progress)
                    self.cam_yaw = start_yaw + (end_yaw - start_yaw) * eased
                    self.cam_pitch = start_pitch + (end_pitch - start_pitch) * eased
                    if progress >= 1.0:
                        self._camera_transition = None

                if pr.is_mouse_button_down(MouseButton.MOUSE_BUTTON_RIGHT):
                    self._camera_transition = None
                    delta = pr.get_mouse_delta()
                    self.cam_yaw -= delta.x * 0.006
                    self.cam_pitch = max(-1.55, min(1.55, self.cam_pitch + delta.y * 0.006))

                wheel = pr.get_mouse_wheel_move()
                if wheel != 0:
                    self.cam_distance = max(8.0, min(120.0, self.cam_distance - wheel * 2.5))

                if pr.is_key_pressed(KeyboardKey.KEY_SPACE):
                    self.simulation_running = not self.simulation_running

                if pr.is_key_pressed(KeyboardKey.KEY_R):
                    self._reset_camera()
                if pr.is_key_pressed(KeyboardKey.KEY_F):
                    self._cycle_follow_drone()
                if pr.is_key_pressed(KeyboardKey.KEY_L):
                    self.show_zone_labels = not self.show_zone_labels
                if pr.is_key_pressed(KeyboardKey.KEY_K):
                    self.show_capacity_gauges = not self.show_capacity_gauges
                if pr.is_key_pressed(KeyboardKey.KEY_T):
                    self.show_trails = not self.show_trails
                if pr.is_key_pressed(KeyboardKey.KEY_M):
                    self.show_minimap = not self.show_minimap
                if pr.is_key_pressed(KeyboardKey.KEY_V):
                    self._toggle_layout_mode()

                if pr.is_key_pressed(KeyboardKey.KEY_BACKSPACE) and self.simulator:
                    self._undo_simulation()
                    self.last_step_time = current_time

                if (
                    pr.is_key_pressed(KeyboardKey.KEY_N) or pr.is_key_pressed(KeyboardKey.KEY_ENTER)
                ) and not all_done and self.simulator:
                    self._advance_simulation()
                    self.last_step_time = current_time

                if self.simulation_running and not all_done and self.simulator:
                    if current_time - self.last_step_time > self.step_interval:
                        self._advance_simulation()
                        self.last_step_time = current_time

            # Mise à jour continue de la caméra 3D
            focus = [0.0, 0.0, 0.0]
            followed = self.follow_drone_id
            if followed is not None and followed in self.drone_positions:
                focus = list(self.drone_positions[followed])
            cam_x = self.cam_distance * math.cos(self.cam_pitch) * math.sin(self.cam_yaw)
            cam_y = self.cam_distance * math.sin(self.cam_pitch)
            cam_z = self.cam_distance * math.cos(self.cam_pitch) * math.cos(self.cam_yaw)
            eye = [focus[0] + cam_x, focus[1] + cam_y, focus[2] + cam_z]
            camera.target = pr.Vector3(*focus)
            camera.position = pr.Vector3(*eye)
            if planet_shader is not None:
                planet_shader.update(eye, focus)
            # Pas de survol de zone pendant les menus.
            if self.app_state == STATE_SIMULATION:
                self.hovered_zone = self._pick_hovered_zone(camera)
            else:
                self.hovered_zone = None

            if drone_model and animations and anim_count[0] > 0:
                anim_frame_counter = (anim_frame_counter + 6.0) % animations[0].keyframeCount
                pr.update_model_animation(drone_model, animations[0], int(anim_frame_counter))

            if self.simulator:
                for drone in self.simulator.drones:
                    # Zone, ou milieu de la connexion si le drone est en vol.
                    anchor = self._drone_anchor(drone.current_location)
                    if anchor is not None:
                        curr = self.drone_positions[drone.id]
                        curr[0] += (anchor[0] - curr[0]) * 0.12
                        curr[1] += (anchor[1] - curr[1]) * 0.12
                        curr[2] += (anchor[2] - curr[2]) * 0.12
                        if self.show_trails:
                            self._track_drone_trail(drone.id, curr)

            # Le fond animé est rendu dans sa RenderTexture AVANT begin_drawing()
            if bg_anim:
                # Le fond est recalculé une image sur deux; la RenderTexture
                # conserve l'image précédente entre deux mises à jour.
                if self.render_frame_index % 2 == 0:
                    bg_anim.render()
                self.render_frame_index += 1

            pr.begin_drawing()
            pr.clear_background(bg_color)

            if bg_anim:
                bg_anim.draw()
            elif bg_texture:
                self._draw_background(bg_texture)

            pr.begin_mode_3d(camera)

            if self.show_connections and self.graph:
                for conn in self.graph.connections_list:
                    p1 = self.node_positions.get(conn.zone1)
                    p2 = self.node_positions.get(conn.zone2)
                    if p1 and p2:
                        waiting = self._pending_link_load(conn.zone1, conn.zone2)
                        capacity = max(1, conn.max_link_capacity)
                        line_color = self._connection_color(waiting / capacity)
                        # Un seul cylindre par lien, coloré selon la charge.
                        _pipe_radius = max(0.042, min(0.10, self.planet_size * 0.075))
                        pr.draw_cylinder_ex(
                            p1, p2, _pipe_radius, _pipe_radius, 8,
                            line_color,
                        )

            if self.simulator:
                low_detail_map = (
                    self.graph is not None
                    and len(self.graph.zones) >= LOW_DETAIL_ZONE_COUNT
                )
                for idx, (zone_name, pos) in enumerate(self.node_positions.items()):
                    size = self.planet_size
                    tint: Any = pr.WHITE
                    is_hub = False

                    if zone_name == self.simulator.start_hub:
                        size *= 1.4
                        tint = [100, 180, 255, 255]
                        is_hub = True
                    elif zone_name == self.simulator.end_hub:
                        size *= 1.4
                        tint = [255, 90, 90, 255]
                        is_hub = True

                    model = planet_model
                    if low_detail_map and not is_hub and planet_models_low:
                        if zone_name not in low_planet_by_zone:
                            low_planet_by_zone[zone_name] = random.choice(
                                planet_models_low
                            )
                        model = low_planet_by_zone[zone_name]

                    if model:
                        # Planète 3D : diamètre = size, rotation lente décalée par zone
                        scale = size / (2.0 * PLANET_MODEL_RADIUS)
                        spin = (current_time * 12.0 + idx * 53.0) % 360.0
                        if planet_shader is not None:
                            planet_shader.set_atmosphere(
                                self._planet_atmosphere_for_zone(zone_name, idx)
                            )
                        pr.draw_model_ex(
                            model, pos, [0.0, 1.0, 0.0], spin,
                            [scale, scale, scale], tint
                        )
                    elif planet_texture is not None:
                        pr.draw_billboard(camera, planet_texture, pos, size, tint)
                    else:
                        pr.draw_sphere(pos, size / 2.0, tint)

                    if self.simulator and zone_name == self.simulator.start_hub:
                        self._draw_hub_ring(pos, size * 0.78, [80, 190, 255, 255])
                    elif self.simulator and zone_name == self.simulator.end_hub:
                        self._draw_hub_ring(pos, size * 0.78, [255, 90, 115, 255])

                if self.show_trails:
                    for trail in self.drone_trails.values():
                        for trail_index in range(1, len(trail)):
                            alpha = max(35, min(180, 35 + trail_index * 9))
                            pr.draw_line_3d(
                                trail[trail_index - 1], trail[trail_index],
                                [50, 190, 255, alpha]
                            )

                for drone in self.simulator.drones:
                    d_pos = self.drone_positions[drone.id]
                    if drone_model:
                        pr.draw_model_ex(
                            drone_model, d_pos, [0.0, 1.0, 0.0], 0.0,
                            [self.drone_scale] * 3, [255, 255, 255, 255]
                        )
                    else:
                        pr.draw_sphere(d_pos, self.planet_size * 0.15, [230, 50, 50, 255])

            pr.end_mode_3d()

            self._draw_zone_overlays(camera)
            self._draw_minimap()

            if self.simulator:
                pr.draw_text(f"Carte : {os.path.basename(self.current_map_path)}", 20, 20, 18, COLOR_CYAN)
                pr.draw_text(f"Tour : {self.simulator.turn}", 20, 45, 22, COLOR_WHITE)
                layout_hud = (
                    "3D PERSONNALISÉE"
                    if self.layout_mode == "custom"
                    else "COORDONNÉES CARTE"
                )
                pr.draw_text(
                    f"Disposition : {layout_hud} (V)",
                    20, 70, 14, COLOR_GRAY,
                )
                delivered_count = sum(
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
                pr.draw_text(
                    "ESPACE : lecture/pause | N/ENTRÉE : tour | RETOUR : annuler | P : menu",
                    20, 90, 14, COLOR_GRAY
                )
                pr.draw_text(
                    "Clic droit : tourner | Molette : zoom | Flèches : vue | "
                    "F : suivre drone | R : reset",
                    20, 108, 13, COLOR_GRAY
                )
                pr.draw_text(
                    "L : noms | K : jauges | T : traînées | M : mini-map | V : disposition",
                    20, 125, 13, COLOR_GRAY
                )

                if self.show_capacity_info and self.graph:
                    y_cap = 155
                    # La liste ne doit pas descendre sous le radar.
                    capacity_limit = self.height - (240 if self.show_minimap else 80)
                    pr.draw_text("--- INFOS CAPACITÉ ---", 20, y_cap, 14, COLOR_YELLOW)
                    for z_name, zone in self.graph.zones.items():
                        y_cap += 18
                        if y_cap > capacity_limit:
                            pr.draw_text("...", 20, y_cap, 14, COLOR_YELLOW)
                            break
                        drones_in_zone = sum(1 for d in self.simulator.drones if d.current_location == z_name)
                        pr.draw_text(f"Zone {z_name}: {drones_in_zone}/{zone.max_drones}", 20, y_cap, 13, COLOR_GOLD)

                # Le radar occupe le coin bas-gauche : messages décalés.
                message_x = 330 if self.show_minimap else 20
                if self.simulator.deadlocked:
                    message = self.simulator.error or "Aucun mouvement possible."
                    pr.draw_text(
                        "SIMULATION BLOQUÉE", message_x, self.height - 50, 22, [255, 80, 80, 255]
                    )
                    pr.draw_text(
                        message[:100], message_x, self.height - 25, 14, [255, 135, 135, 255]
                    )
                elif all_done:
                    pr.draw_text(
                        "TOUS LES DRONES SONT ARRIVÉS !",
                        message_x, self.height - 50, 22, [50, 220, 100, 255]
                    )

            if self.app_state == STATE_MENU_MAIN:
                if self._draw_main_menu() == "EXIT":
                    break
            elif self.app_state == STATE_MENU_MAPS:
                self._draw_maps_menu()
            elif self.app_state == STATE_MENU_OPTIONS:
                self._draw_options_menu()

            pr.end_drawing()

        if animations and anim_count[0] > 0:
            pr.unload_model_animations(animations, anim_count[0])
        if drone_model:
            pr.unload_model(drone_model)
        if planet_shader is not None:
            planet_shader.unload()
        if planet_model is not None:
            pr.unload_model(planet_model)
        for loaded_model in planet_models_low:
            pr.unload_model(loaded_model)
        if planet_texture:
            pr.unload_texture(planet_texture)
        if bg_anim:
            bg_anim.unload()
        if bg_texture:
            pr.unload_texture(bg_texture)

        pr.close_window()