from typing import Dict, List, Optional, Tuple

from graph import NetworkGraph
from models import Drone


class Simulator:
    """Simule les drones en respectant les capacités des zones et des liaisons.

    Les déplacements sont traités dans un ordre déterministe : chemin restant le
    plus court, puis identifiant du drone. Une liaison physique ne peut être
    empruntée qu'un nombre de fois égal à sa capacité pendant un même tour,
    quel que soit le sens du déplacement.
    """

    def __init__(
        self,
        graph: NetworkGraph,
        start_hub: str,
        end_hub: str,
        nb_drones: int,
        paths: List[List[str]],
    ) -> None:
        if nb_drones < 0:
            raise ValueError("Le nombre de drones ne peut pas être négatif.")
        if start_hub not in graph.zones:
            raise ValueError(f"Le hub de départ '{start_hub}' n'existe pas.")
        if end_hub not in graph.zones:
            raise ValueError(f"Le hub d'arrivée '{end_hub}' n'existe pas.")
        if start_hub == end_hub:
            raise ValueError("Le hub de départ et d'arrivée doivent être différents.")
        if nb_drones > 0 and not paths:
            raise ValueError("Impossible de simuler des drones sans chemin valide.")

        self.graph = graph
        self.start_hub = start_hub
        self.end_hub = end_hub
        self.nb_drones = nb_drones
        self.turn = 0
        self.error: Optional[str] = None
        self.deadlocked = False
        self._waited_this_turn = False

        validated_paths = [
            self._validate_path(path, index)
            for index, path in enumerate(paths, 1)
        ]

        # Répartition équilibrée : on privilégie le chemin le plus court et le
        # moins chargé. On retire le hub de départ, déjà occupé initialement.
        path_loads = [0] * len(validated_paths)
        path_assignments: List[List[str]] = []
        for _ in range(nb_drones):
            best_path_idx = min(
                range(len(validated_paths)),
                key=lambda idx: len(validated_paths[idx]) + path_loads[idx],
            )
            path_assignments.append(validated_paths[best_path_idx][1:])
            path_loads[best_path_idx] += 1

        self.drones: List[Drone] = [
            Drone(
                id=f"D{index}",
                current_location=start_hub,
                path=path_assignments[index - 1],
                turns_spent_in_zone=1,
            )
            for index in range(1, nb_drones + 1)
        ]

        self.zone_occupancy: Dict[str, int] = {
            zone_name: 0 for zone_name in graph.zones
        }
        self.zone_occupancy[start_hub] = nb_drones

    def _validate_path(self, path: List[str], path_number: int) -> List[str]:
        """Vérifie la structure du chemin avant de lancer la simulation."""
        if not path:
            raise ValueError(f"Le chemin {path_number} est vide.")
        if path[0] != self.start_hub:
            raise ValueError(
                f"Le chemin {path_number} doit commencer par '{self.start_hub}'."
            )
        if path[-1] != self.end_hub:
            raise ValueError(
                f"Le chemin {path_number} doit se terminer par '{self.end_hub}'."
            )

        for zone_name in path:
            if zone_name not in self.graph.zones:
                raise ValueError(
                    f"Le chemin {path_number} contient la zone inconnue '{zone_name}'."
                )
            if self.graph.is_blocked(zone_name):
                raise ValueError(
                    f"Le chemin {path_number} traverse la zone bloquée '{zone_name}'."
                )

        for origin, target in zip(path, path[1:]):
            if target not in self.graph.get_neighbors(origin):
                raise ValueError(
                    f"Le chemin {path_number} contient une liaison inexistante : "
                    f"'{origin}' -> '{target}'."
                )
            if self.graph.get_link_capacity(origin, target) <= 0:
                raise ValueError(
                    f"La liaison '{origin}' -> '{target}' n'a pas de capacité positive."
                )

        return list(path)

    def is_finished(self) -> bool:
        """Retourne True si tous les drones sont livrés (y compris zéro drone)."""
        return all(drone.status == "delivered" for drone in self.drones)

    def run(self) -> bool:
        """Exécute la simulation et retourne True uniquement si elle est terminée.

        La simulation s'arrête dès qu'aucun mouvement ni attente réglementaire
        n'est possible. Cela évite les boucles infinies en cas de deadlock.
        """
        while not self.is_finished():
            self.turn += 1
            moves_this_turn = self._simulate_turn()

            if moves_this_turn:
                print(" ".join(moves_this_turn))
                continue

            if self.is_finished():
                break

            # Un drone peut ne pas bouger pendant un tour parce qu'il termine son
            # délai obligatoire dans une zone restreinte. Ce cas est temporaire.
            if self._waited_this_turn:
                continue

            self.deadlocked = True
            self.error = (
                f"Deadlock détecté au tour {self.turn} : "
                "aucun mouvement possible."
            )
            print(f"Error: {self.error}")
            return False

        return self.is_finished()

    @staticmethod
    def _physical_link(origin: str, target: str) -> Tuple[str, str]:
        """Identifie une liaison sans tenir compte du sens de circulation."""
        return (origin, target) if origin <= target else (target, origin)

    def _simulate_turn(self) -> List[str]:
        """Effectue un tour et renvoie les mouvements réellement exécutés."""
        moves: List[str] = []
        self._waited_this_turn = False
        link_usage: Dict[Tuple[str, str], int] = {}

        # Ordre stable : un drone proche de sa destination passe en premier.
        drones_to_process = sorted(
            (drone for drone in self.drones if drone.status != "delivered"),
            key=lambda drone: (len(drone.path), drone.id),
        )

        for drone in drones_to_process:
            current_zone = self.graph.get_zone(drone.current_location)
            if current_zone is None:
                self.error = (
                    f"La zone actuelle '{drone.current_location}' du drone "
                    f"{drone.id} n'existe pas."
                )
                continue

            # Entrer dans une zone restreinte compte comme le premier tour.
            # Le drone attend un tour supplémentaire, puis peut repartir.
            if current_zone.zone_type == "restricted" and drone.turns_spent_in_zone < 2:
                drone.turns_spent_in_zone += 1
                self._waited_this_turn = True
                continue

            if not drone.path:
                self.error = (
                    f"Le drone {drone.id} n'a plus de chemin avant d'atteindre "
                    f"'{self.end_hub}'."
                )
                continue

            next_target = drone.path[0]
            target_zone = self.graph.get_zone(next_target)
            if target_zone is None or self.graph.is_blocked(next_target):
                self.error = f"Destination invalide '{next_target}' pour {drone.id}."
                continue
            if next_target not in self.graph.get_neighbors(drone.current_location):
                self.error = (
                    f"Liaison invalide pour {drone.id} : "
                    f"'{drone.current_location}' -> '{next_target}'."
                )
                continue

            link = self._physical_link(drone.current_location, next_target)
            link_capacity = self.graph.get_link_capacity(
                drone.current_location, next_target
            )
            if link_capacity <= 0 or link_usage.get(link, 0) >= link_capacity:
                continue

            # Le hub d'arrivée accepte tous les drones ; les autres zones
            # respectent strictement max_drones.
            if (
                next_target != self.end_hub
                and self.zone_occupancy[next_target] >= target_zone.max_drones
            ):
                continue

            origin = drone.current_location
            self.zone_occupancy[origin] -= 1
            drone.current_location = next_target
            drone.path.pop(0)
            drone.turns_spent_in_zone = 1
            link_usage[link] = link_usage.get(link, 0) + 1

            if next_target == self.end_hub:
                drone.status = "delivered"
            else:
                self.zone_occupancy[next_target] += 1
                drone.status = "waiting"

            moves.append(f"{drone.id}-{next_target}")

        return moves