from typing import List, Dict, Set
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
        
        # Initialisation des drones avec leur identifiant (D1, D2...) et leur chemin
        self.drones: List[Drone] = []
        for i in range(1, nb_drones + 1):
            # best_path contient [start, zoneA, zoneB, end]
            # On retire le start car le drone y est déjà
            path_to_follow = best_path[1:] if best_path else []
            self.drones.append(Drone(id=f"D{i}", current_location=start_hub, path=path_to_follow))

        # Suivi de l'occupation instantanée pour la gestion des capacités
        self.zone_occupancy: Dict[str, int] = {zone_name: 0 for zone_name in self.graph.zones.keys()}
        self.zone_occupancy[self.start_hub] = nb_drones # Le start_hub n'a pas de limite

    def is_finished(self) -> bool:
        """Vérifie si tous les drones sont arrivés à destination."""
        return all(drone.status == "delivered" for drone in self.drones)

    def run(self) -> None:
        """Boucle principale de la simulation."""
        while not self.is_finished():
            self.turn += 1
            moves_this_turn = self._simulate_turn()
            
            if not moves_this_turn:
                print(f"Error: Deadlock détecté au tour {self.turn} (Aucun drone ne peut bouger).")
                break
                
            # Affichage exact demandé par le sujet : D1-roof1 D2-corridorA
            print(" ".join(moves_this_turn))

    def _simulate_turn(self) -> List[str]:
        """Gère la logique d'un seul tour et retourne la liste des mouvements formatés."""
        moves: List[str] = []
        
        # On trie les drones en fonction de leur proximité avec l'arrivée pour éviter de se bloquer
        # Ceux qui ont le chemin restant le plus court bougent en premier
        drones_to_move = sorted(
            [d for d in self.drones if d.status != "delivered"],
            key=lambda d: len(d.path)
        )

        # 1. Phase de libération (les drones qui quittent une zone libèrent la place)
        # Géré dynamiquement ci-dessous lors du mouvement effectif

        for drone in drones_to_move:
            if not drone.path:
                continue
                
            next_target = drone.path[0]
            target_zone = self.graph.get_zone(next_target)
            
            if not target_zone:
                continue

            # Vérification de la capacité de la zone cible
            # Le start_hub et end_hub ont une capacité infinie
            has_space = False
            if target_target == self.end_hub:
                has_space = True
            else:
                has_space = self.zone_occupancy[next_target] < target_zone.max_drones

            # TODO: Implémenter la vérification de self.graph.get_link_capacity() si nécessaire

            if has_space:
                # Le drone peut bouger !
                # Il libère son ancienne zone (sauf si c'est le start_hub)
                if drone.current_location != self.start_hub:
                    self.zone_occupancy[drone.current_location] -= 1
                
                # Il occupe la nouvelle zone (sauf si c'est le end_hub)
                if next_target != self.end_hub:
                    self.zone_occupancy[next_target] += 1
                
                # Formatage de la sortie
                if target_zone.zone_type == "restricted" and drone.status != "in_transit":
                    # Cas spécial : zone restreinte (prend 2 tours)
                    drone.status = "in_transit"
                    connection_name = f"{drone.current_location}-{next_target}"
                    moves.append(f"{drone.id}-{connection_name}")
                else:
                    # Mouvement normal ou finalisation du transit
                    drone.current_location = next_target
                    drone.path.pop(0) # Retire la zone atteinte du chemin restant
                    
                    if next_target == self.end_hub:
                        drone.status = "delivered"
                    else:
                        drone.status = "waiting"
                        
                    moves.append(f"{drone.id}-{next_target}")

        return moves