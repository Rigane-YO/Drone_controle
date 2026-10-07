import math
import time
import os
from typing import Dict, List
import pyray as pr

from graph import NetworkGraph
from simulation import Simulator


class Visualizer3D:
    def __init__(self, graph: NetworkGraph, simulator: Simulator) -> None:
        self.graph = graph
        self.simulator = simulator

        self.node_positions: Dict[str, List[float]] = {}
        self.drone_positions: Dict[str, List[float]] = {}

        self.width = 1200
        self.height = 800

        # --- CALCUL DYNAMIQUE DES TAILLES ET DISTANCES ---
        self.num_nodes = max(1, len(self.graph.zones))
        
        # Ajustement des rayons d'agencement selon le nombre de zones
        self.radius_x = max(10.0, min(35.0, math.sqrt(self.num_nodes) * 4.5))
        self.radius_z = max(6.0, min(22.0, math.sqrt(self.num_nodes) * 3.0))

        # Tailles adaptatives : grandes cartes -> petits objets ; petites cartes -> grands objets
        self.planet_size = max(1.2, min(4.2, 28.0 / math.sqrt(self.num_nodes)))
        self.drone_scale = max(0.04, min(0.14, 0.8 / math.sqrt(self.num_nodes)))

        self._compute_3d_layout()
        self._init_drones()

    def _compute_3d_layout(self) -> None:
        """Répartit les planètes sur 4 anneaux avec rayons dynamiques."""
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
            
            # Échelle progressive selon les anneaux et le nombre de nœuds
            r_x = (self.radius_x * 0.25) + ring_idx * (self.radius_x * 0.25)
            r_z = (self.radius_z * 0.25) + ring_idx * (self.radius_z * 0.25)

            items_per_ring = max(1, n // num_rings)
            ring_pos = i // num_rings
            angle = (2 * math.pi * ring_pos / items_per_ring) + (ring_idx * 0.8)

            x = r_x * math.cos(angle)
            z = r_z * math.sin(angle)
            y = math.sin(i * 1.5) * (1.2 if self.num_nodes < 20 else 0.8)

            self.node_positions[zone_name] = [x, y, z]

    def _init_drones(self) -> None:
        start_pos = self.node_positions.get(
            self.simulator.start_hub, [0.0, 0.0, 0.0]
        )
        for drone in self.simulator.drones:
            self.drone_positions[drone.id] = [
                start_pos[0], start_pos[1] + (self.planet_size * 0.6), start_pos[2]
            ]

    def _all_drones_delivered(self) -> bool:
        for drone in self.simulator.drones:
            if drone.current_location != self.simulator.end_hub:
                return False
        return True

    def _load_planet_texture(self):
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

    def run(self) -> None:
        pr.init_window(self.width, self.height, "Fly-in : Visualisation 3D")
        pr.set_target_fps(60)

        planet_texture = self._load_planet_texture()

        bg_texture = None
        bg_path = os.path.join("assets", "abstract.jpg")
        if os.path.exists(bg_path):
            bg_texture = pr.load_texture(bg_path)
            pr.set_texture_filter(bg_texture, pr.TEXTURE_FILTER_BILINEAR)

        model_path = os.path.join("assets", "drone.glb")
        drone_model = None
        animations = None
        anim_count = pr.ffi.new("int *")
        anim_frame_counter = 0.0

        if os.path.exists(model_path):
            try:
                drone_model = pr.load_model(model_path)
                animations = pr.load_model_animations(model_path, anim_count)
            except Exception:
                pass

        simulation_running = False
        last_step_time = time.time()
        step_interval = 0.8

        bg_color = [2, 2, 8, 255]
        line_color = [0, 120, 160, 180]

        # Caméra avec hauteur et recul adaptatifs
        cam_y = max(20.0, self.radius_z * 1.8)
        cam_z = max(22.0, self.radius_z * 1.5)
        camera = pr.Camera3D(
            [0.0, cam_y, cam_z],
            [0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            55.0,
            0
        )

        while not pr.window_should_close():
            current_time = time.time()
            all_done = self._all_drones_delivered()

            if pr.is_key_pressed(pr.KEY_SPACE):
                simulation_running = not simulation_running

            if pr.is_key_pressed(pr.KEY_RIGHT) and not all_done:
                self.simulator.turn += 1
                self.simulator._simulate_turn()

            if simulation_running and not all_done:
                if current_time - last_step_time > step_interval:
                    self.simulator.turn += 1
                    self.simulator._simulate_turn()
                    last_step_time = current_time

            if drone_model and animations and anim_count[0] > 0:
                anim_frame_counter += 6.0
                total_frames = animations[0].keyframeCount
                if anim_frame_counter >= total_frames:
                    anim_frame_counter %= total_frames
                pr.update_model_animation(
                    drone_model, animations[0], int(anim_frame_counter)
                )

            for drone in self.simulator.drones:
                target_zone_name = drone.current_location
                if target_zone_name in self.node_positions:
                    target_pos = self.node_positions[target_zone_name]
                    curr = self.drone_positions[drone.id]
                    curr[0] += (target_pos[0] - curr[0]) * 0.12
                    curr[1] += ((target_pos[1] + self.planet_size * 0.5) - curr[1]) * 0.12
                    curr[2] += (target_pos[2] - curr[2]) * 0.12

            pr.begin_drawing()
            pr.clear_background(bg_color)
            if bg_texture:
                self._draw_background(bg_texture)

            pr.begin_mode_3d(camera)

            # A. Connexions du réseau
            for conn in self.graph.connections_list:
                p1 = self.node_positions.get(conn.zone1)
                p2 = self.node_positions.get(conn.zone2)
                if p1 and p2:
                    pr.draw_line_3d(p1, p2, line_color)

            # B. Planètes en Billboard (Taille dynamique)
            for zone_name, pos in self.node_positions.items():
                p_size = self.planet_size
                if zone_name in (self.simulator.start_hub, self.simulator.end_hub):
                    p_size *= 1.4

                pr.draw_billboard(camera, planet_texture, pos, p_size, pr.WHITE)

            # C. Drones (Echelle dynamique)
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

            # HUD
            pr.draw_text(f"Tour : {self.simulator.turn}", 20, 20, 22, pr.RAYWHITE)
            pr.draw_text("ESPACE : Lancer/Pause | -> : Tour suivant", 20, 50, 16, pr.GRAY)

            if all_done:
                pr.draw_text("TOUS LES DRONES SONT ARRIVES !", 20, 80, 22, [50, 220, 100, 255])

            pr.end_drawing()

        if animations and anim_count[0] > 0:
            pr.unload_model_animations(animations, anim_count[0])
        if drone_model:
            pr.unload_model(drone_model)
        pr.unload_texture(planet_texture)
        if bg_texture:
            pr.unload_texture(bg_texture)
        pr.close_window()