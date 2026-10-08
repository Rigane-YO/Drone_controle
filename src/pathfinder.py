import heapq
from typing import Dict, List, Optional, Set, Tuple

from graph import NetworkGraph


class Pathfinder:
    """Recherche des chemins peu coûteux dans le réseau de drones."""

    def __init__(self, graph: NetworkGraph, start: str, end: str) -> None:
        self.graph = graph
        self.start = start
        self.end = end

    @staticmethod
    def _edge_key(zone1: str, zone2: str) -> Tuple[str, str]:
        """Retourne une représentation canonique d'une liaison non orientée."""
        return (zone1, zone2) if zone1 <= zone2 else (zone2, zone1)

    def _valid_endpoints(self) -> bool:
        """Un chemin exige deux hubs distincts, existants et non bloqués."""
        return (
            self.start != self.end
            and self.start in self.graph.zones
            and self.end in self.graph.zones
            and not self.graph.is_blocked(self.start)
            and not self.graph.is_blocked(self.end)
        )

    def _get_zone_weight(self, zone_name: str) -> float:
        """Détermine le coût algorithmique de traversée d'une zone."""
        zone = self.graph.get_zone(zone_name)
        if zone is None or zone.zone_type == "blocked":
            return float("inf")
        if zone.zone_type == "restricted":
            return 2.0
        if zone.zone_type == "priority":
            return 0.5
        return 1.0

    def find_shortest_path(self) -> Optional[List[str]]:
        """Trouve un chemin de coût minimal avec Dijkstra."""
        if not self._valid_endpoints():
            return None
        return self._find_path_excluding(set(), set())

    def find_multiple_disjoint_paths(self) -> List[List[str]]:
        """Trouve des chemins sans zones intermédiaires ni liaisons partagées.

        La recherche est gloutonne, elle ne garantit donc pas de maximiser le
        nombre total de chemins trouvés. Les liaisons déjà utilisées sont aussi
        exclues pour empêcher de retrouver indéfiniment un chemin direct
        start_hub -> end_hub, qui ne contient aucun nœud intermédiaire.
        """
        if not self._valid_endpoints():
            return []

        paths: List[List[str]] = []
        excluded_nodes: Set[str] = set()
        excluded_edges: Set[Tuple[str, str]] = set()
        seen_paths: Set[Tuple[str, ...]] = set()

        while True:
            path = self._find_path_excluding(excluded_nodes, excluded_edges)
            if path is None:
                break

            signature = tuple(path)
            # Défense supplémentaire : une répétition ne doit jamais boucler.
            if signature in seen_paths:
                break
            seen_paths.add(signature)
            paths.append(path)

            excluded_nodes.update(path[1:-1])
            for zone1, zone2 in zip(path, path[1:]):
                excluded_edges.add(self._edge_key(zone1, zone2))

        return paths

    def _find_path_excluding(
        self,
        excluded_nodes: Set[str],
        excluded_edges: Optional[Set[Tuple[str, str]]] = None,
    ) -> Optional[List[str]]:
        """Dijkstra en ignorant des nœuds et liaisons déjà réservés."""
        if not self._valid_endpoints():
            return None

        blocked_edges = excluded_edges if excluded_edges is not None else set()
        queue: List[Tuple[float, str]] = [(0.0, self.start)]
        came_from: Dict[str, Optional[str]] = {self.start: None}
        cost_so_far: Dict[str, float] = {self.start: 0.0}

        while queue:
            current_cost, current_zone = heapq.heappop(queue)
            if current_cost > cost_so_far.get(current_zone, float("inf")):
                continue
            if current_zone == self.end:
                break

            for next_zone in self.graph.get_neighbors(current_zone):
                edge = self._edge_key(current_zone, next_zone)
                if edge in blocked_edges:
                    continue
                if next_zone in excluded_nodes or next_zone == self.start:
                    continue
                if self.graph.is_blocked(next_zone):
                    continue
                if self.graph.get_link_capacity(current_zone, next_zone) <= 0:
                    continue

                weight = self._get_zone_weight(next_zone)
                if weight == float("inf"):
                    continue
                new_cost = current_cost + weight

                if new_cost < cost_so_far.get(next_zone, float("inf")):
                    cost_so_far[next_zone] = new_cost
                    came_from[next_zone] = current_zone
                    heapq.heappush(queue, (new_cost, next_zone))

        return self._reconstruct_path(came_from)

    def _reconstruct_path(
        self, came_from: Dict[str, Optional[str]]
    ) -> Optional[List[str]]:
        if self.end not in came_from:
            return None

        path: List[str] = []
        current: Optional[str] = self.end
        while current is not None:
            path.append(current)
            current = came_from.get(current)
        path.reverse()
        return path