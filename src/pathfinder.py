import heapq
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from graph import NetworkGraph


@dataclass
class _FlowEdge:
    """Arc résiduelle d'un réseau de flot à coût minimal."""

    to: int
    reverse_index: int
    capacity: int
    cost: int
    initial_capacity: int


class Pathfinder:
    """Recherche des chemins courts et un ensemble maximal de routes.

    Les routes retournées ne partagent aucune zone intermédiaire. Le nombre
    de routes est maximisé en premier; parmi ces solutions, le coût total est
    minimisé afin de favoriser les zones priority et d'éviter restricted.
    """

    def __init__(self, graph: NetworkGraph, start: str, end: str) -> None:
        self.graph = graph
        self.start = start
        self.end = end

    def _valid_endpoints(self) -> bool:
        """Vérifie que les deux hubs existent et sont accessibles."""
        return (
            self.start != self.end
            and self.start in self.graph.zones
            and self.end in self.graph.zones
            and not self.graph.is_blocked(self.start)
            and not self.graph.is_blocked(self.end)
        )

    def _get_zone_weight(self, zone_name: str) -> float:
        """Retourne le coût de traversée; faible est préférable."""
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
        """Retourne un maximum de chemins aux zones intermédiaires disjointes.

        Un flot entier sur un graphe avec séparation des sommets permet de
        maximiser le nombre de chemins de façon globale. Les capacités des
        sommets intermédiaires valent 1; les hubs peuvent accueillir plusieurs
        flux. Un flot de coût minimal favorise ensuite les itinéraires courts
        et les zones ``priority``. Les liaisons de capacité nulle sont
        ignorées.
        """
        if not self._valid_endpoints():
            return []

        zone_names = list(self.graph.zones.keys())
        zone_index = {name: index for index, name in enumerate(zone_names)}
        vertex_count = 2 * len(zone_names)
        residual: List[List[_FlowEdge]] = [[] for _ in range(vertex_count)]
        infinity = max(2, len(self.graph.connections_list) + 1)

        def node_in(zone_name: str) -> int:
            return 2 * zone_index[zone_name]

        def node_out(zone_name: str) -> int:
            return 2 * zone_index[zone_name] + 1

        def add_edge(
            origin: int, target: int, capacity: int, cost: int
        ) -> _FlowEdge:
            forward = _FlowEdge(
                to=target,
                reverse_index=len(residual[target]),
                capacity=capacity,
                cost=cost,
                initial_capacity=capacity,
            )
            reverse = _FlowEdge(
                to=origin,
                reverse_index=len(residual[origin]),
                capacity=0,
                cost=-cost,
                initial_capacity=0,
            )
            residual[origin].append(forward)
            residual[target].append(reverse)
            return forward

        # Séparation in/out : capacité 1 pour chaque zone intermédiaire.
        for zone_name in zone_names:
            zone = self.graph.get_zone(zone_name)
            if zone is None or zone.zone_type == "blocked":
                capacity = 0
                cost = 0
            elif zone_name in {self.start, self.end}:
                capacity = infinity
                cost = 0
            else:
                capacity = 1
                # Échelle entière: priority=0.5, normal=1, restricted=2.
                # Les coûts entiers évitent les erreurs flottantes.
                weight = self._get_zone_weight(zone_name)
                cost = int(weight * 2)
            add_edge(node_in(zone_name), node_out(zone_name), capacity, cost)

        # Une route indépendante ne réutilise pas de zone intermédiaire.
        # Les arcs physiques sont unitaires, notamment la liaison directe
        # start-end qui ne doit compter qu'une seule fois.
        transition_edges: Dict[Tuple[str, str], _FlowEdge] = {}
        for connection in self.graph.connections_list:
            first = connection.zone1
            second = connection.zone2
            if first == second:
                continue
            if first not in zone_index or second not in zone_index:
                continue
            if self.graph.get_link_capacity(first, second) <= 0:
                continue
            if self.graph.is_blocked(first) or self.graph.is_blocked(second):
                continue
            transition_edges[(first, second)] = add_edge(
                node_out(first), node_in(second), 1, 0
            )
            transition_edges[(second, first)] = add_edge(
                node_out(second), node_in(first), 1, 0
            )

        source = node_out(self.start)
        sink = node_out(self.end)
        flow = 0
        node_count = len(residual)

        # Successive shortest augmenting paths, Bellman-Ford étant nécessaire
        # pour les arcs résiduels négatifs créés lors des réaffectations.
        while True:
            distances: List[float] = [float("inf")] * node_count
            parent_node: List[Optional[int]] = [None] * node_count
            parent_edge: List[Optional[int]] = [None] * node_count
            distances[source] = 0

            for _ in range(node_count - 1):
                changed = False
                for origin in range(node_count):
                    if distances[origin] == float("inf"):
                        continue
                    for edge_index, edge in enumerate(residual[origin]):
                        if edge.capacity <= 0:
                            continue
                        candidate = distances[origin] + edge.cost
                        if candidate < distances[edge.to]:
                            distances[edge.to] = candidate
                            parent_node[edge.to] = origin
                            parent_edge[edge.to] = edge_index
                            changed = True
                if not changed:
                    break

            if parent_node[sink] is None:
                break

            amount = infinity
            current = sink
            while current != source:
                origin = parent_node[current]
                edge_index = parent_edge[current]
                if origin is None or edge_index is None:
                    amount = 0
                    break
                amount = min(amount, residual[origin][edge_index].capacity)
                current = origin
            if amount <= 0 or amount == infinity:
                break

            current = sink
            while current != source:
                origin = parent_node[current]
                edge_index = parent_edge[current]
                # La boucle précédente garantit ces valeurs.
                assert origin is not None and edge_index is not None
                edge = residual[origin][edge_index]
                edge.capacity -= amount
                residual[edge.to][edge.reverse_index].capacity += amount
                current = origin
            flow += amount

        # Décompose le flot entier en chemins du départ vers l'arrivée.
        remaining_flow: Dict[Tuple[str, str], int] = {
            pair: edge.initial_capacity - edge.capacity
            for pair, edge in transition_edges.items()
        }
        paths: List[List[str]] = []
        max_path_length = len(zone_names) + 1

        for _ in range(flow):
            path = [self.start]
            seen = {self.start}
            current = self.start

            while current != self.end and len(path) < max_path_length:
                next_zone: Optional[str] = None
                for neighbor in self.graph.get_neighbors(current):
                    if remaining_flow.get((current, neighbor), 0) > 0:
                        if neighbor not in seen:
                            next_zone = neighbor
                            break
                if next_zone is None:
                    break
                path.append(next_zone)
                seen.add(next_zone)
                current = next_zone

            if current != self.end:
                # Défense contre un flot résiduel incohérent; pas de boucle.
                break

            for origin, target in zip(path, path[1:]):
                remaining_flow[(origin, target)] -= 1
            paths.append(path)

        # Présente d'abord les chemins de moindre coût, tout en gardant le
        # nombre maximal obtenu par le flot.
        paths.sort(
            key=lambda path: (self._path_cost(path), len(path), tuple(path))
        )
        return paths

    def _path_cost(self, path: List[str]) -> float:
        """Calcule le coût total, hors hubs de départ et d'arrivée."""
        return sum(self._get_zone_weight(zone) for zone in path[1:-1])

    def _find_path_excluding(
        self,
        excluded_nodes: Set[str],
        excluded_edges: Optional[Set[Tuple[str, str]]] = None,
    ) -> Optional[List[str]]:
        """Dijkstra avec exclusion facultative de zones et de liaisons."""
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
                if next_zone in excluded_nodes or next_zone == self.start:
                    continue
                if self.graph.is_blocked(next_zone):
                    continue
                if self.graph.get_link_capacity(current_zone, next_zone) <= 0:
                    continue
                edge_key = (
                    (current_zone, next_zone)
                    if current_zone <= next_zone
                    else (next_zone, current_zone)
                )
                if edge_key in blocked_edges:
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
        current: Optional[str] = self.end
        path: List[str] = []
        while current is not None:
            path.append(current)
            current = came_from.get(current)
        path.reverse()
        return path