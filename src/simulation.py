from typing import List, Dict
from models import Drone, Zone
from graph import NetworkGraph

class Simulator:
    """Moteur de simulation tour par tour pour le réseau de drones."""

    def __init__(self, graph: NetworkGraph, start_hub: str, end_hub: str, nb_drones: int, best_path: List[str]) -> None:
        self.graph: NetworkGraph = graph
        self.start_hub: str = start_hub
        self.end_hub: str = end_hub
        self.nb_drones: int = nb_drones
        self.turn: int = 0
        
        self.drones: List[Drone] = []
        for i in range(1, nb_drones + 1):
            path_to_follow = best_path[1:] if best_path else []
            self.drones.append(
                Drone(
                    id=f"D{i}",
                    current_location=start_hub,
                    path=path_to_follow,
                    turns_spent_in_zone=1  # Le start_hub ne bloque pas
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
            
            # Vérification si la simulation est bloquée (deadlock)
            if not moves_this_turn and not self.is_finished():
                # On vérifie si au moins un drone est simplement en train d'attendre son 2e tour
                waiting_in_restricted = any(
                    d.status != "delivered" and 
                    self.graph.get_zone(d.current_location) and 
                    self.graph.get_zone(d.current_location).zone_type == "restricted" and 
                    d.turns_spent_in_zone < 2
                    for d in self.drones
                )
                if not waiting_in_restricted:
                    print(f"Error: Deadlock détecté au tour {self.turn}.")
                    break
                
            if moves_this_turn:
                print(" ".join(moves_this_turn))

    def _simulate_turn(self) -> List[str]:
        """Gère la logique d'un seul tour et retourne les mouvements effectifs."""
        moves: List[str] = []
        
        # Priorité aux drones les plus proches de l'arrivée
        drones_to_process = sorted(
            [d for d in self.drones if d.status != "delivered"],
            key=lambda d: len(d.path)
        )

        for drone in drones_to_process:
            current_zone = self.graph.get_zone(drone.current_location)
            
            # 1. Règle des zones restreintes : arrêt obligatoire de 2 tours
            if current_zone and current_zone.zone_type == "restricted":
                if drone.turns_spent_in_zone < 2:
                    # Le drone effectue son 2e tour dans la zone, il ne peut pas bouger
                    drone.turns_spent_in_zone += 1
                    continue

            # Si le drone n'a plus de zones à parcourir, il est arrivé
            if not drone.path:
                continue

            next_target = drone.path[0]
            target_zone = self.graph.get_zone(next_target)

            if not target_zone:
                continue

            # Vérification de la capacité de la zone cible
            has_space = (next_target == self.end_hub) or (self.zone_occupancy[next_target] < target_zone.max_drones)

            if has_space:
                # Libération de l'ancienne zone (sauf start_hub)
                if drone.current_location != self.start_hub:
                    self.zone_occupancy[drone.current_location] -= 1

                # Déplacement vers la zone cible
                drone.current_location = next_target
                drone.turns_spent_in_zone = 1  # 1er tour dans la nouvelle zone
                drone.path.pop(0)

                # Occupation de la nouvelle zone (sauf end_hub)
                if next_target != self.end_hub:
                    self.zone_occupancy[next_target] += 1
                    drone.status = "waiting"
                else:
                    drone.status = "delivered"

                moves.append(f"{drone.id}-{next_target}")

        return moves