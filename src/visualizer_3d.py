import math
import os
import time
from typing import Dict, List, Optional, Tuple

import pyray as pr

from graph import NetworkGraph
from simulation import Simulator
from intro_video import IntroVideo
from parser import parse_map_file


# États de l'interface
STATE_SIMULATION = 0
STATE_MENU_MAIN = 1
STATE_MENU_MAPS = 2
STATE_MENU_OPTIONS = 3

# Définition de couleurs RGBA personnalisées (100% compatibles PyRay)
COLOR_CYAN = [0, 200, 255, 255]
COLOR_GOLD = [255, 203, 0, 255]
COLOR_YELLOW = [255, 249, 0, 255]
COLOR_GRAY = [130, 130, 130, 255]
COLOR_WHITE = [245, 245, 245, 255]

# Rayon de la sphère dans Blender (RADIUS dans lava_planet_blender.py).
# Sert à ajuster l'échelle du modèle : diamètre affiché = planet_size.
PLANET_MODEL_RADIUS = 2.0

# Fond animé (assets/abstract.glb) : caméra alignée sur l'aperçu du script Blender.
# Conversion Blender (x, y, z) -> raylib (x, z, -y).
BG_CAMERA_POS = [0.0, 13.0, 8.0]
BG_CAMERA_TARGET = [0.0, 0.0, -1.0]
BG_CAMERA_FOVY = 50.0
BG_CLEAR_COLOR = [2, 2, 8, 255]
BG_RENDER_SCALE = 1.0   # 1.5 ou 2.0 = bords plus lisses (rendu plus lourd)
BG_ANIM_SPEED = 1.0     # images d'animation avancées à chaque image affichée


class AnimatedBackground:
    """Fond 3D animé (animation squelettique d'un GLB), rendu dans une RenderTexture
    avec sa propre caméra, puis affiché en plein écran derrière la scène principale."""

    def __init__(self, path: str, width: int, height: int) -> None:
        self.model = pr.load_model(path)
        self.anim_count = pr.ffi.new("int *")
        self.animations = pr.load_model_animations(path, self.anim_count)
        self.frame = 0.0
        self.target = pr.load_render_texture(
            int(width * BG_RENDER_SCALE), int(height * BG_RENDER_SCALE)
        )
        pr.set_texture_filter(self.target.texture, pr.TEXTURE_FILTER_BILINEAR)
        self.camera = pr.Camera3D(
            BG_CAMERA_POS, BG_CAMERA_TARGET, [0.0, 1.0, 0.0], BG_CAMERA_FOVY, 0
        )

    def _frame_count(self) -> int:
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
        sw, sh = pr.get_screen_width(), pr.get_screen_height()
        tex = self.target.texture
        src = pr.Rectangle(0, 0, tex.width, -tex.height)   # RenderTexture inversée en Y
        dst = pr.Rectangle(0, 0, sw, sh)
        pr.draw_texture_pro(tex, src, dst, pr.Vector2(0, 0), 0.0, pr.WHITE)
        pr.draw_rectangle(0, 0, sw, sh, [0, 0, 0, darken])

    def unload(self) -> None:
        if self.animations and self.anim_count[0] > 0:
            pr.unload_model_animations(self.animations, self.anim_count[0])
        pr.unload_model(self.model)
        pr.unload_render_texture(self.target)


class Visualizer3D:
    def __init__(
        self,
        graph: Optional[NetworkGraph] = None,
        simulator: Optional[Simulator] = None,
        map_path: str = "maps/easy/linear.txt"
    ) -> None:
        self.width = 1200
        self.height = 800

        self.node_positions: Dict[str, List[float]] = {}
        self.drone_positions: Dict[str, List[float]] = {}

        # Options de simulation / affichage
        self.show_capacity_info = False  # Flag --capacity-info
        self.step_interval = 0.8         # Vitesse de simulation
        self.show_connections = True

        # Contrôle de la caméra sphérique (Attributs d'instance)
        self.cam_distance = 35.0
        self.cam_yaw = 0.0
        self.cam_pitch = 0.95

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
        self.cam_distance = max(35.0, self.radius_z * 2.2)
        self.cam_yaw = 0.0
        self.cam_pitch = 0.95

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

        num_rings = 4 if n >= 12 else (2 if n >= 6 else 1)

        for i, zone_name in enumerate(internal_zones):
            ring_idx = i % num_rings
            radius_x = (self.radius_x * 0.25) + ring_idx * (self.radius_x * 0.25)
            radius_z = (self.radius_z * 0.25) + ring_idx * (self.radius_z * 0.25)

            items_per_ring = max(1, n // num_rings)
            ring_pos = i // num_rings

            angle = ((2 * math.pi * ring_pos / items_per_ring) + (ring_idx * 0.9))

            x = radius_x * math.cos(angle)
            z = radius_z * math.sin(angle)
            y = math.sin(i * 1.5) * 1.0

            self.node_positions[zone_name] = [x, y, z]

    def _init_drones(self) -> None:
        if not self.simulator:
            return
        start_pos = self.node_positions.get(self.simulator.start_hub, [0.0, 0.0, 0.0])
        for drone in self.simulator.drones:
            self.drone_positions[drone.id] = [
                start_pos[0],
                start_pos[1] + (self.planet_size * 0.5),
                start_pos[2]
            ]

    def _restart_simulation(self) -> None:
        if self.current_map_path:
            self._load_map(self.current_map_path)

    def _all_drones_delivered(self) -> bool:
        if not self.simulator:
            return True
        for drone in self.simulator.drones:
            if drone.current_location != self.simulator.end_hub:
                return False
        return True

    def _load_planet_model(self):
        """Charge assets/planet.glb (planète volcanique). Retourne None si absent."""
        path = os.path.join("assets", "planet.glb")
        if os.path.exists(path):
            try:
                return pr.load_model(path)
            except Exception as e:
                print(f"⚠ Erreur modèle planète : {e}")
        return None

    def _load_planet_texture(self):
        """Repli : ancienne planète 2D (billboard) si le GLB est introuvable."""
        path = os.path.join("assets", "planet.png")
        if os.path.exists(path):
            texture = pr.load_texture(path)
            pr.set_texture_filter(texture, pr.TEXTURE_FILTER_BILINEAR)
            return texture

        img = pr.gen_image_color(100, 100, pr.BLANK)
        pr.image_draw_circle(img, 50, 50, 45, pr.DARKBLUE)
        texture = pr.load_texture_from_image(img)
        pr.unload_image(img)
        return texture

    def _draw_background(self, texture, darken: int = 110) -> None:
        sw, sh = pr.get_screen_width(), pr.get_screen_height()
        tw, th = texture.width, texture.height
        scale = max(sw / tw, sh / th)
        src_w, src_h = sw / scale, sh / scale

        src = pr.Rectangle((tw - src_w) / 2, (th - src_h) / 2, src_w, src_h)
        dst = pr.Rectangle(0, 0, sw, sh)

        pr.draw_texture_pro(texture, src, dst, pr.Vector2(0, 0), 0.0, pr.WHITE)
        pr.draw_rectangle(0, 0, sw, sh, [0, 0, 0, darken])

    def _draw_button(self, rect: Tuple[float, float, float, float], text: str) -> bool:
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

        return is_hovered and pr.is_mouse_button_pressed(pr.MOUSE_BUTTON_LEFT)

    def _draw_main_menu(self) -> Optional[str]:
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
        pr.draw_rectangle(0, 0, self.width, self.height, [5, 10, 20, 230])
        pr.draw_text("SELECTION DE LA CARTE", 50, 40, 32, COLOR_CYAN)

        categories = ["easy", "medium", "hard", "challenger", "other"]
        tab_x = 50
        for cat in categories:
            rect = (tab_x, 90, 110, 35)
            if self._draw_button(rect, cat.upper()):
                self.current_category = cat
            tab_x += 120

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
        pr.draw_rectangle(0, 0, self.width, self.height, [5, 10, 20, 230])
        pr.draw_text("OPTIONS DE VISUALISATION", 50, 40, 32, COLOR_CYAN)

        cap_status = "ACTIVÉ" if self.show_capacity_info else "DÉSACTIVÉ"
        if self._draw_button((60, 130, 450, 45), f"INFOS CAPACITÉ (--capacity-info) : {cap_status}"):
            self.show_capacity_info = not self.show_capacity_info

        conn_status = "ACTIVÉ" if self.show_connections else "DÉSACTIVÉ"
        if self._draw_button((60, 190, 450, 45), f"AFFICHER CONNEXIONS : {conn_status}"):
            self.show_connections = not self.show_connections

        speed_label = f"VITESSE PAS A PAS : {self.step_interval:.1f}s"
        pr.draw_text(speed_label, 60, 260, 20, COLOR_WHITE)
        if self._draw_button((60, 290, 100, 35), "- 0.2s"):
            self.step_interval = max(0.1, self.step_interval - 0.2)
        if self._draw_button((170, 290, 100, 35), "+ 0.2s"):
            self.step_interval = min(3.0, self.step_interval + 0.2)

        if self._draw_button((50, self.height - 70, 180, 45), "◄ RETOUR"):
            self.app_state = STATE_MENU_MAIN

    def run(self) -> None:
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
        planet_model = self._load_planet_model()
        planet_texture = None if planet_model else self._load_planet_texture()

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
            pr.set_texture_filter(bg_texture, pr.TEXTURE_FILTER_BILINEAR)

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
        line_color = [0, 120, 160, 180]

        camera = pr.Camera3D([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 55.0, 0)

        while not pr.window_should_close():
            current_time = time.time()
            all_done = self._all_drones_delivered()

            # TOUCHE P : Ouvrir / Fermer le menu Pause
            if pr.is_key_pressed(pr.KEY_P):
                if self.app_state == STATE_SIMULATION:
                    self.app_state = STATE_MENU_MAIN
                else:
                    self.app_state = STATE_SIMULATION

            if self.app_state == STATE_SIMULATION:
                if pr.is_key_pressed(pr.KEY_UP):
                    self.cam_yaw, self.cam_pitch = 0.0, 1.55
                elif pr.is_key_pressed(pr.KEY_DOWN):
                    self.cam_yaw, self.cam_pitch = 0.0, 0.05
                elif pr.is_key_pressed(pr.KEY_LEFT):
                    self.cam_yaw, self.cam_pitch = -math.pi / 2, 0.1
                elif pr.is_key_pressed(pr.KEY_RIGHT):
                    self.cam_yaw, self.cam_pitch = math.pi / 2, 0.1

                if pr.is_mouse_button_down(pr.MOUSE_BUTTON_MIDDLE):
                    delta = pr.get_mouse_delta()
                    self.cam_yaw -= delta.x * 0.006
                    self.cam_pitch = max(-1.55, min(1.55, self.cam_pitch + delta.y * 0.006))

                wheel = pr.get_mouse_wheel_move()
                if wheel != 0:
                    self.cam_distance = max(8.0, min(120.0, self.cam_distance - wheel * 2.5))

                if pr.is_key_pressed(pr.KEY_SPACE):
                    self.simulation_running = not self.simulation_running

                if (pr.is_key_pressed(pr.KEY_N) or pr.is_key_pressed(pr.KEY_ENTER)) and not all_done and self.simulator:
                    self.simulator.turn += 1
                    self.simulator._simulate_turn()

                if self.simulation_running and not all_done and self.simulator:
                    if current_time - self.last_step_time > self.step_interval:
                        self.simulator.turn += 1
                        self.simulator._simulate_turn()
                        self.last_step_time = current_time

            # Mise à jour continue de la caméra 3D
            cam_x = self.cam_distance * math.cos(self.cam_pitch) * math.sin(self.cam_yaw)
            cam_y = self.cam_distance * math.sin(self.cam_pitch)
            cam_z = self.cam_distance * math.cos(self.cam_pitch) * math.cos(self.cam_yaw)
            camera.position = [cam_x, cam_y, cam_z]

            if drone_model and animations and anim_count[0] > 0:
                anim_frame_counter = (anim_frame_counter + 6.0) % animations[0].keyframeCount
                pr.update_model_animation(drone_model, animations[0], int(anim_frame_counter))

            if self.simulator:
                for drone in self.simulator.drones:
                    target_zone_name = drone.current_location
                    if target_zone_name in self.node_positions:
                        target_pos = self.node_positions[target_zone_name]
                        curr = self.drone_positions[drone.id]
                        curr[0] += (target_pos[0] - curr[0]) * 0.12
                        curr[1] += ((target_pos[1] + self.planet_size * 0.5) - curr[1]) * 0.12
                        curr[2] += (target_pos[2] - curr[2]) * 0.12

            # Le fond animé est rendu dans sa RenderTexture AVANT begin_drawing()
            if bg_anim:
                bg_anim.render()

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
                        pr.draw_line_3d(p1, p2, line_color)

            if self.simulator:
                for idx, (zone_name, pos) in enumerate(self.node_positions.items()):
                    size = self.planet_size
                    tint = pr.WHITE

                    if zone_name == self.simulator.start_hub:
                        size *= 1.4
                        tint = [100, 180, 255, 255]
                    elif zone_name == self.simulator.end_hub:
                        size *= 1.4
                        tint = [255, 90, 90, 255]

                    if planet_model:
                        # Planète 3D : diamètre = size, rotation lente décalée par zone
                        scale = size / (2.0 * PLANET_MODEL_RADIUS)
                        spin = (current_time * 12.0 + idx * 53.0) % 360.0
                        pr.draw_model_ex(
                            planet_model, pos, [0.0, 1.0, 0.0], spin,
                            [scale, scale, scale], tint
                        )
                    else:
                        pr.draw_billboard(camera, planet_texture, pos, size, tint)

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

            if self.simulator:
                pr.draw_text(f"Carte : {os.path.basename(self.current_map_path)}", 20, 20, 18, COLOR_CYAN)
                pr.draw_text(f"Tour : {self.simulator.turn}", 20, 45, 22, COLOR_WHITE)
                pr.draw_text("ESPACE : Pause | N / ENTRÉE : Pas à Pas | P : Menu", 20, 75, 15, COLOR_GRAY)

                if self.show_capacity_info and self.graph:
                    y_cap = 100
                    pr.draw_text("--- INFOS CAPACITÉ ---", 20, y_cap, 14, COLOR_YELLOW)
                    for z_name, zone in self.graph.zones.items():
                        y_cap += 18
                        if y_cap > self.height - 80:
                            pr.draw_text("...", 20, y_cap, 14, COLOR_YELLOW)
                            break
                        drones_in_zone = sum(1 for d in self.simulator.drones if d.current_location == z_name)
                        pr.draw_text(f"Zone {z_name}: {drones_in_zone}/{zone.max_drones}", 20, y_cap, 13, COLOR_GOLD)

                if all_done:
                    pr.draw_text("TOUS LES DRONES SONT ARRIVÉS !", 20, self.height - 50, 22, [50, 220, 100, 255])

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
        if planet_model:
            pr.unload_model(planet_model)
        if planet_texture:
            pr.unload_texture(planet_texture)
        if bg_anim:
            bg_anim.unload()
        if bg_texture:
            pr.unload_texture(bg_texture)

        pr.close_window()