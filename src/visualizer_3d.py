import math
import time
import os
from typing import Dict, List
import pyray as pr

from graph import NetworkGraph
from simulation import Simulator


class Visualizer3D:
    """Visualiseur 3D corrigé pour le projet Fly-in (42)."""

    def __init__(self, graph: NetworkGraph, simulator: Simulator) -> None:
        self.graph = graph
        self.simulator = simulator

        self.node_positions: Dict[str, List[float]] = {}
        self.drone_positions: Dict[str, List[float]] = {}

        self.width = 1200
        self.height = 800

        self._compute_3d_layout()
        self._init_drones()

    def _compute_3d_layout(self) -> None:
        """Calcule la disposition des zones sur le plan 3D."""
        zones = list(self.graph.zones.keys())
        n = len(zones)
        radius = 8.0

        for i, zone_name in enumerate(zones):
            if zone_name == self.simulator.start_hub:
                self.node_positions[zone_name] = [-12.0, 0.0, 0.0]
            elif zone_name == self.simulator.end_hub:
                self.node_positions[zone_name] = [12.0, 0.0, 0.0]
            else:
                angle = 2 * math.pi * i / max(1, n - 2)
                x = radius * math.cos(angle)
                z = radius * math.sin(angle)
                y = math.sin(i * 2.0) * 1.5
                self.node_positions[zone_name] = [x, y, z]

    def _init_drones(self) -> None:
        """Positionne tous les drones au start_hub."""
        start_pos = self.node_positions.get(self.simulator.start_hub, [0.0, 0.0, 0.0])
        for drone in self.simulator.drones:
            # On les élève légèrement au-dessus du nœud (+1.2 en Y) pour qu'ils soient bien visibles
            self.drone_positions[drone.id] = [start_pos[0], start_pos[1] + 1.2, start_pos[2]]

    def _all_drones_delivered(self) -> bool:
        """Vérifie rigoureusement si TOUS les drones sont arrivés à destination."""
        for drone in self.simulator.drones:
            if drone.current_location != self.simulator.end_hub:
                return False
        return True

    def run(self) -> None:
        """Boucle principale de rendu 3D."""
        pr.init_window(self.width, self.height, "Fly-in : Visualisation 3D")
        pr.set_target_fps(60)

        # --- CHARGEMENT SÛR DU MODÈLE BLENDER ---
        model_path = os.path.join("assets", "drone.glb")
        drone_model = None
        animations = None
        anim_count = pr.ffi.new("int *")
        anim_frame_counter = 0

        if os.path.exists(model_path):
            try:
                drone_model = pr.load_model(model_path)
                animations = pr.load_model_animations(model_path, anim_count)
                print(f"✓ Modèle 3D '{model_path}' chargé avec succès !")
            except Exception as e:
                print(f"⚠️ Erreur de chargement du modèle 3D : {e}")
        else:
            print(f"⚠️ Fichier introuvable : {os.path.abspath(model_path)}")

        simulation_running = False
        last_step_time = time.time()
        step_interval = 0.8  # Seconde entre chaque tour

        bg_color = [20, 20, 28, 255]
        line_color = [80, 80, 110, 255]

        # Caméra stable
        camera = pr.Camera3D(
            [0.0, 16.0, 24.0],  # Position
            [0.0, 0.0, 0.0],    # Cible
            [0.0, 1.0, 0.0],    # Vecteur haut
            45.0,               # FOV
            0
        )

        while not pr.window_should_close():
            current_time = time.time()
            all_done = self._all_drones_delivered()

            # --- 1. CONTRÔLES ---
            if pr.is_key_pressed(pr.KEY_SPACE):
                simulation_running = not simulation_running

            # Flèche droite : avancer d'un tour manuellement
            if pr.is_key_pressed(pr.KEY_RIGHT) and not all_done:
                self.simulator.turn += 1
                self.simulator._simulate_turn()

            # Avancement automatique pas à pas
            if simulation_running and not all_done:
                if current_time - last_step_time > step_interval:
                    self.simulator.turn += 1
                    self.simulator._simulate_turn()
                    last_step_time = current_time

            # --- 2. ANIMATION DES HÉLICES (BLENDER) ---
            if drone_model and animations and anim_count[0] > 0:
                anim_frame_counter += 1
                pr.update_model_animation(drone_model, animations[0], anim_frame_counter)
                if anim_frame_counter >= animations[0].frameCount:
                    anim_frame_counter = 0

            # --- 3. DÉPLACEMENT LISSÉ ET ORIENTATION DES DRONES ---
            for drone in self.simulator.drones:
                target_zone_name = drone.current_location
                if target_zone_name in self.node_positions:
                    target_pos = self.node_positions[target_zone_name]
                    curr = self.drone_positions[drone.id]
                    
                    # Interpolation fluide vers le nœud cible (au-dessus du nœud Y + 1.2)
                    curr[0] += (target_pos[0] - curr[0]) * 0.12
                    curr[1] += ((target_pos[1] + 1.2) - curr[1]) * 0.12
                    curr[2] += (target_pos[2] - curr[2]) * 0.12

            # --- 4. RENDU 3D ---
            pr.begin_drawing()
            pr.clear_background(bg_color)
            pr.begin_mode_3d(camera)

            # A. Connexions du réseau
            for conn in self.graph.connections_list:
                p1 = self.node_positions.get(conn.zone1)
                p2 = self.node_positions.get(conn.zone2)
                if p1 and p2:
                    pr.draw_line_3d(p1, p2, line_color)

            # B. Zones (Nœuds 3D)
            for zone_name, pos in self.node_positions.items():
                zone = self.graph.get_zone(zone_name)
                color = [160, 160, 175, 255]

                if zone:
                    if zone.zone_type == "restricted":
                        color = [230, 120, 30, 255]   # Orange
                    elif zone.zone_type == "priority":
                        color = [40, 190, 90, 255]    # Vert
                    elif zone.zone_type == "blocked":
                        color = [210, 40, 40, 255]    # Rouge

                if zone_name == self.simulator.start_hub:
                    color = [40, 120, 230, 255]      # Bleu Départ
                elif zone_name == self.simulator.end_hub:
                    color = [230, 190, 30, 255]      # Jaune Arrivée

                pr.draw_sphere(pos, 0.6, color)
                pr.draw_sphere_wires(pos, 0.6, 8, 8, [30, 30, 40, 255])

            # C. Rendu des Drones
            for drone in self.simulator.drones:
                d_pos = self.drone_positions[drone.id]

                if drone_model:
                    # Affichage du modèle 3D Blender
                    pr.draw_model_ex(
                        drone_model,
                        d_pos,
                        [0.0, 1.0, 0.0],
                        0.0,
                        [0.4, 0.4, 0.4],             # Échelle augmentée à 0.4 pour bien le voir !
                        [255, 255, 255, 255]         # Couleurs d'origine
                    )
                else:
                    # Rendu visuel alternatif si le fichier .glb manque
                    pr.draw_sphere(d_pos, 0.3, [230, 50, 50, 255])
                    pr.draw_cylinder_wires(d_pos, 0.4, 0.4, 0.1, 6, pr.WHITE)

            pr.end_mode_3d()

            # --- 5. INTERFACE HUD ---
            pr.draw_text(f"Tour : {self.simulator.turn}", 20, 20, 22, pr.RAYWHITE)
            pr.draw_text("ESPACE : Lancer/Pause | -> : Tour suivant", 20, 50, 16, pr.GRAY)

            if all_done:
                pr.draw_text("TOUS LES DRONES SONT ARRIVES !", 20, 80, 22, [50, 220, 100, 255])

            pr.end_drawing()

        # Nettoyage
        if animations and anim_count[0] > 0:
            pr.unload_model_animations(animations, anim_count[0])
        if drone_model:
            pr.unload_model(drone_model)

        pr.close_window()