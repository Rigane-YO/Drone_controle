import heapq
from typing import Dict, List, Tuple, Optional
from graph import NetworkGraph

class Pathfinder:
    """Gère la recherche de chemins optimisés dans le réseau de drones."""

    def __init__(self, graph: NetworkGraph, start: str, end: str) -> None:
        self.graph: NetworkGraph = graph
        self.start: str = start
        self.end: str = end

    def _get_zone_weight(self, zone_name: str) -> float:
        """Détermine le coût de traversée algorithmique d'une zone."""
        zone = self.graph.get_zone(zone_name)
        if not zone:
            return float('inf')
            
        if zone.zone_type == "restricted":
            return 2.0
        elif zone.zone_type == "priority":
            return 0.5 
        elif zone.zone_type == "blocked":
            return float('inf')
        return 1.0

    def find_shortest_path(self) -> Optional[List[str]]:
        """
        Trouve le chemin le plus court (algorithme de Dijkstra) de start à end.
        Retourne la liste des noms de zones constituant le chemin, ou None si aucun chemin.
        """
        queue: List[Tuple[float, str]] = [(0.0, self.start)]
        
        came_from: Dict[str, Optional[str]] = {self.start: None}
        
        cost_so_far: Dict[str, float] = {self.start: 0.0}

        while queue:
            current_cost, current_zone = heapq.heappop(queue)

            if current_zone == self.end:
                break

            for next_zone in self.graph.get_neighbors(current_zone):
                if self.graph.is_blocked(next_zone):
                    continue

                new_cost = cost_so_far[current_zone] + self._get_zone_weight(next_zone)
                if next_zone not in cost_so_far or new_cost < cost_so_far[next_zone]:
                    cost_so_far[next_zone] = new_cost
                    heapq.heappush(queue, (new_cost, next_zone))
                    came_from[next_zone] = current_zone

        return self._reconstruct_path(came_from)

    def _reconstruct_path(self, came_from: Dict[str, Optional[str]]) -> Optional[List[str]]:
        """Reconstruit la liste des zones du début à la fin en remontant le dictionnaire."""
        if self.end not in came_from:
            return None

        current: Optional[str] = self.end
        path: List[str] = []
        
        while current is not None:
            path.append(current)
            current = came_from.get(current)
            
        path.reverse()
        return path