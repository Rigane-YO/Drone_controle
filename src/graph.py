from typing import Dict, List, Optional, Tuple
from models import Zone, Connection

class NetworkGraph:
    """Gère la topologie du réseau et permet de naviguer entre les zones."""
    
    def __init__(self, zones: Dict[str, Zone], connections: List[Connection]) -> None:
        self.zones: Dict[str, Zone] = zones
        self.connections_list: List[Connection] = connections
        self.adjacency_list: Dict[str, List[str]] = {name: [] for name in zones.keys()}
        self.link_capacities: Dict[Tuple[str, str], int] = {}
        
        self._build_graph()

    def _build_graph(self) -> None:
        """Construit la liste d'adjacence bidirectionnelle et indexe les capacités."""
        for conn in self.connections_list:
            self.adjacency_list[conn.zone1].append(conn.zone2)
            self.adjacency_list[conn.zone2].append(conn.zone1)
            self.link_capacities[(conn.zone1, conn.zone2)] = conn.max_link_capacity
            self.link_capacities[(conn.zone2, conn.zone1)] = conn.max_link_capacity

    def get_neighbors(self, zone_name: str) -> List[str]:
        """Retourne la liste des noms des zones adjacentes."""
        return self.adjacency_list.get(zone_name, [])

    def get_zone(self, zone_name: str) -> Optional[Zone]:
        """Retourne l'objet Zone complet correspondant au nom."""
        return self.zones.get(zone_name)

    def get_link_capacity(self, zone1: str, zone2: str) -> int:
        """Retourne la capacité maximale de la connexion entre deux zones."""
        return self.link_capacities.get((zone1, zone2), 0)
        
    def is_blocked(self, zone_name: str) -> bool:
        """Vérifie si une zone est bloquée et donc inaccessible."""
        zone = self.get_zone(zone_name)
        return zone is not None and zone.zone_type == "blocked"