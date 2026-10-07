from typing import List, Dict
from models import Drone, Zone
from graph import NetworkGraph

class Simulator:
    """Moteur de simulation tour par tour pour le réseau de drones."""

    def __init__(self, graph: NetworkGraph, start_hub: str, end_hub: str, nb_drones: int, paths: List[List[str]]) -> None:
        self.graph: NetworkGraph = graph
        self.start_hub: str = start_hub
        self.end_hub: str = end_hub
        self.nb_drones: int = nb_drones
        self.turn: int = 0
        
        # Répartition intelligente des drones sur les différents chemins disponibles
        path_assignments: List[List[str]] = [[] for _ in range(nb_drones)]
        path_loads = [0] * len(paths)
        
        for i in range(nb_drones):
            best_path_idx = min(
                range(len(paths)),
                key=lambda idx: len(paths[idx]) + path_loads[idx]
            )
            path_assignments[i] = paths[best_path_idx][1:]  # On retire le start_hub
            path_loads[best_path_idx] += 1

        self.drones: List[Drone] = []
        for i in range(1, nb_drones + 1):
            self.drones.append(
                Drone(
                    id=f"D{i}",
                    current_location=start_hub,
                    path=path_assignments[i - 1],
                    turns_spent_in_zone=1
                )
            )

        self.zone_occupancy: Dict[str, int] = {zone_name: 0 for zone_name in self.graph.zones.keys()}
        self.zone_occupancy[self.start_hub] = nb_drones

    def is_finished(self) -> bool:
        """Vérifie si tous les drones sont arrivés à destination."""
        return all(drone.status == "delivered" for drone in self.drones)

    def run(self) -> None:
            """Boucle principale de la simulation."""
            while not self.is_finished():
                self.turn += 1
                moves_this_turn = self._simulate_turn()
                
                if not moves_this_turn and not self.is_finished():
                    # Vérification intelligente : s'il y a un drone dans une zone restreinte,
                    # ce n'est pas un deadlock, il est juste en train de purger son timer de 2 tours.
                    waiting_in_restricted = any(
                        d.status != "delivered" and 
                        self.graph.get_zone(d.current_location) and 
                        self.graph.get_zone(d.current_location).zone_type == "restricted"
                        for d in self.drones
                    )
                    
                    if not waiting_in_restricted:
                        print(f"Error: Deadlock détecté au tour {self.turn}.")
                        break
                    else:
                        # On laisse passer ce tour d'attente sans couper la simulation
                        continue
                    
                if moves_this_turn:
                    print(" ".join(moves_this_turn))

    def _simulate_turn(self) -> List[str]:
        """Gère la logique d'un seul tour et retourne les mouvements effectifs."""
        moves: List[str] = []
        
        drones_to_process = sorted(
            [d for d in self.drones if d.status != "delivered"],
            key=lambda d: len(d.path)
        )

        for drone in drones_to_process:
            current_zone = self.graph.get_zone(drone.current_location)
            
            # 1. Règle des zones restreintes : arrêt obligatoire de 2 tours
            if current_zone and current_zone.zone_type == "restricted":
                if drone.turns_spent_in_zone < 2:
                    drone.turns_spent_in_zone += 1
                    continue

            if not drone.path:
                continue

            next_target = drone.path[0]
            target_zone = self.graph.get_zone(next_target)

            if not target_zone:
                continue

            has_space = (next_target == self.end_hub) or (self.zone_occupancy[next_target] < target_zone.max_drones)

            if has_space:
                if drone.current_location != self.start_hub:
                    self.zone_occupancy[drone.current_location] -= 1

                drone.current_location = next_target
                drone.turns_spent_in_zone = 1
                drone.path.pop(0)

                if next_target == self.end_hub:
                    drone.status = "delivered"
                else:
                    self.zone_occupancy[next_target] += 1
                    drone.status = "waiting"

                moves.append(f"{drone.id}-{next_target}")

        return moves