from typing import Dict, List, Optional, Tuple

from models import Connection, Zone


class NetworkGraph:
    """Gère la topologie du réseau de zones et les capacités des liaisons."""

    def __init__(self, zones: Dict[str, Zone], connections: List[Connection]) -> None:
        self.zones = zones
        self.connections_list = connections
        self.adjacency_list: Dict[str, List[str]] = {
            name: [] for name in zones
        }
        self.link_capacities: Dict[Tuple[str, str], int] = {}
        self._build_graph()

    def _build_graph(self) -> None:
        for connection in self.connections_list:
            self.adjacency_list[connection.zone1].append(connection.zone2)
            self.adjacency_list[connection.zone2].append(connection.zone1)
            self.link_capacities[(connection.zone1, connection.zone2)] = (
                connection.max_link_capacity
            )
            self.link_capacities[(connection.zone2, connection.zone1)] = (
                connection.max_link_capacity
            )

    def get_neighbors(self, zone_name: str) -> List[str]:
        return self.adjacency_list.get(zone_name, [])

    def get_zone(self, zone_name: str) -> Optional[Zone]:
        return self.zones.get(zone_name)

    def get_link_capacity(self, zone1: str, zone2: str) -> int:
        return self.link_capacities.get((zone1, zone2), 0)

    def is_blocked(self, zone_name: str) -> bool:
        zone = self.get_zone(zone_name)
        return zone is not None and zone.zone_type == "blocked"