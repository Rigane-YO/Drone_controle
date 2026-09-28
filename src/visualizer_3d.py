import math
import time
from typing import Dict, List
import pyray as pr

from graph import NetworkGraph
from simulation import Simulator

class Visualizer3D:
    """Visualiseur 3D en Raylib pour le routage de drones (Projet 42)."""

    def __init__(self, graph: NetworkGraph, simulator: Simulator) -> None:
        self.graph = graph
        self.simulator = simulator
        
        # On utilise des listes Python [x, y, z] à la place de Vector3()
        self.node_positions: Dict[str, List[float]] = {}
        self.drone_positions: Dict[str, List[float]] = {}
        
        # Dimensions de la fenêtre
        self.width = 1200
        self.height = 800
        
        self._compute_3d_layout()
        self._init_drones()

    def _compute_3d_layout(self) -> None:
        """Calcule une disposition en anneau 3D (cylindrique) pour les zones."""
        zones = list(self.graph.zones.keys())
        n = len(zones)
        radius = 8.0

        for i, zone_name in enumerate(zones):
            if zone_name == self.simulator.start_hub:
                # Le départ est excentré (X=-12)
                self.node_positions[zone_name] = [-12.0, 0.0, 0.0]
            elif zone_name == self.simulator.end_hub:
                # L'arrivée est excentrée (X=12)
                self.node_positions[zone_name] = [12.0, 0.0, 0.0]
            else:
                # Les zones intermédiaires forment un cercle en 3D
                angle = 2 * math.pi * i / max(1, n - 2)
                x = radius * math.cos(angle)
                z = radius * math.sin(angle)
                y = math.sin(i * 2.0) * 2.0
                self.node_positions[zone_name] = [x, y, z]

    def _init_drones(self) -> None:
        """Place initialement tous les drones sur la position du start_hub."""
        start_pos = self.node_positions.get(self.simulator.start_hub, [0.0, 0.0, 0.0])
        for drone in self.simulator.drones:
            self.drone_positions[drone.id] = [start_pos[0], start_pos[1] + 1.0, start_pos[2]]

    def run(self) -> None:
        """Boucle principale de rendu 3D avec pyray."""
        pr.init_window(self.width, self.height, "Fly-in 3D - Simulation de Drones (42)")
        
        # Configuration de la caméra 3D
        # pr.Camera3D(position, target, up_vector, fov, projection_mode)
        # 0 correspond à pr.CAMERA_PERSPECTIVE
        camera = pr.Camera3D(
            [0.0, 15.0, 22.0], 
            [0.0, 0.0, 0.0],   
            [0.0, 1.0, 0.0],   
            45.0,              
            0                  
        )

        pr.set_target_fps(60)

        simulation_running = False
        last_step_time = time.time()
        step_interval = 0.8

        # Couleurs personnalisées passées en RGBA
        bg_color = [20, 20, 28, 255]
        line_color = [70, 70, 90, 255]

        while not pr.window_should_close():
            # Gestion du clavier
            if pr.is_key_pressed(pr.KEY_SPACE):
                simulation_running = not simulation_running
            if pr.is_key_pressed(pr.KEY_RIGHT) and not self.simulator.is_finished():
                self.simulator.turn += 1
                self.simulator._simulate_turn()

            if simulation_running and not self.simulator.is_finished():
                current_time = time.time()
                if current_time - last_step_time > step_interval:
                    self.simulator.turn += 1
                    self.simulator._simulate_turn()
                    last_step_time = current_time

            # Mise à jour des positions visuelles des drones
            for drone in self.simulator.drones:
                target_zone_name = drone.current_location
                if target_zone_name in self.node_positions:
                    target_pos = self.node_positions[target_zone_name]
                    curr = self.drone_positions[drone.id]
                    # Interpolation lissée (lerp)
                    curr[0] += (target_pos[0] - curr[0]) * 0.1
                    curr[1] += ((target_pos[1] + 0.8) - curr[1]) * 0.1
                    curr[2] += (target_pos[2] - curr[2]) * 0.1

            # --- DÉBUT DU RENDU ---
            pr.begin_drawing()
            pr.clear_background(bg_color)

            pr.begin_mode_3d(camera)

            # 1. Dessin des connexions (arêtes du graphe)
            for conn in self.graph.connections_list:
                p1 = self.node_positions.get(conn.zone1)
                p2 = self.node_positions.get(conn.zone2)
                if p1 and p2:
                    pr.draw_line_3d(p1, p2, line_color)

            # 2. Dessin des zones (nœuds 3D)
            for zone_name, pos in self.node_positions.items():
                zone = self.graph.get_zone(zone_name)
                color = pr.LIGHTGRAY
                
                if zone:
                    if zone.zone_type == "restricted":
                        color = pr.ORANGE
                    elif zone.zone_type == "priority":
                        color = pr.GREEN
                    elif zone.zone_type == "blocked":
                        color = pr.RED

                if zone_name == self.simulator.start_hub:
                    color = pr.BLUE
                elif zone_name == self.simulator.end_hub:
                    color = pr.YELLOW

                pr.draw_sphere(pos, 0.6, color)
                pr.draw_sphere_wires(pos, 0.6, 8, 8, pr.DARKGRAY)

            # 3. Dessin des drones
            for drone in self.simulator.drones:
                if drone.status != "delivered":
                    d_pos = self.drone_positions[drone.id]
                    pr.draw_sphere(d_pos, 0.35, pr.MAGENTA)
                    pr.draw_sphere_wires(d_pos, 0.35, 4, 4, pr.WHITE)

            pr.end_mode_3d()

            # --- HUD (2D par-dessus la 3D) ---
            pr.draw_text(f"Tour: {self.simulator.turn}", 20, 20, 20, pr.RAYWHITE)
            pr.draw_text("ESPACE: Lancer/Pause | -> : Tour suivant", 20, 50, 16, pr.GRAY)
            if self.simulator.is_finished():
                pr.draw_text("SIMULATION TERMINEE !", 20, 80, 22, pr.GREEN)

            pr.end_drawing()

        pr.close_window()