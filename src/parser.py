import re
from typing import Dict, List, Optional, Tuple

from models import Zone, Connection
from graph import NetworkGraph
from pathfinder import Pathfinder
from simulation import Simulator


class ParsingError(Exception):
    """Exception personnalisée levée lors d'une erreur de syntaxe dans le fichier."""
    def __init__(self, message: str, line_number: int) -> None:
        super().__init__(f"Error line {line_number}: {message}")


class GraphParser:
    def __init__(self, filepath: str) -> None:
        self.filepath: str = filepath
        self.nb_drones: int = 0
        self.zones: Dict[str, Zone] = {}
        self.connections: List[Connection] = []
        self.start_hub: Optional[str] = None
        self.end_hub: Optional[str] = None
        self._parsed_links: set[Tuple[str, str]] = set()

    def parse(self) -> None:
        """Point d'entrée principal qui lit le fichier et construit le graphe."""
        with open(self.filepath, 'r', encoding='utf-8') as file:
            for line_number, line in enumerate(file, start=1):
                clean_line = line.split('#')[0].strip()
                if not clean_line:
                    continue
                
                self._parse_line(clean_line, line_number)
        
        self._validate_graph()

    def _parse_line(self, line: str, line_number: int) -> None:
        """Route la ligne vers la bonne méthode de traitement selon son préfixe."""
        if line.startswith("nb_drones:"):
            self._parse_nb_drones(line, line_number)
        elif line.startswith("start_hub:") or line.startswith("end_hub:") or line.startswith("hub:"):
            self._parse_hub(line, line_number)
        elif line.startswith("connection:"):
            self._parse_connection(line, line_number)
        else:
            raise ParsingError("Invalid syntax or unknown prefix.", line_number)

    def _parse_nb_drones(self, line: str, line_number: int) -> None:
        """Extrait le nombre total de drones."""
        match = re.match(r"^nb_drones:\s+(\d+)$", line)
        if not match:
            raise ParsingError("Invalid nb_drones format. Must be a positive integer.", line_number)
        
        self.nb_drones = int(match.group(1))
        if self.nb_drones <= 0:
            raise ParsingError("Number of drones must be greater than 0.", line_number)

    def _parse_hub(self, line: str, line_number: int) -> None:
        """Extrait les propriétés d'une zone."""
        regex = r"^(start_hub|end_hub|hub):\s+([^\s\-]+)\s+(-?\d+)\s+(-?\d+)(?:\s+\[(.*?)\])?$"
        match = re.match(regex, line)
        
        if not match:
            raise ParsingError("Invalid hub format or zone name contains dashes.", line_number)
        
        hub_type, name, x_str, y_str, meta_str = match.groups()
        
        if name in self.zones:
            raise ParsingError(f"Duplicate zone name: {name}", line_number)

        x, y = int(x_str), int(y_str)
        metadata = self._extract_metadata(meta_str, line_number)

        zone_type = metadata.get("zone", "normal")
        if zone_type not in ["normal", "blocked", "restricted", "priority"]:
            raise ParsingError(f"Invalid zone type: {zone_type}", line_number)

        try:
            max_drones = int(metadata.get("max_drones", 1))
        except ValueError:
            raise ParsingError("max_drones must be an integer.", line_number)
            
        if max_drones <= 0:
            raise ParsingError("max_drones must be a positive integer.", line_number)

        zone = Zone(
            name=name,
            x=x,
            y=y,
            zone_type=zone_type,
            color=metadata.get("color"),
            max_drones=max_drones
        )
        self.zones[name] = zone
        if hub_type == "start_hub":
            if self.start_hub:
                raise ParsingError("Multiple start_hub defined.", line_number)
            self.start_hub = name
        elif hub_type == "end_hub":
            if self.end_hub:
                raise ParsingError("Multiple end_hub defined.", line_number)
            self.end_hub = name

    def _parse_connection(self, line: str, line_number: int) -> None:
        """Extrait une connexion entre deux zones."""
        match = re.match(r"^connection:\s+([^\s\-]+)-([^\s\-]+)(?:\s+\[(.*?)\])?$", line)
        if not match:
            raise ParsingError("Invalid connection format.", line_number)

        zone1, zone2, meta_str = match.groups()

        if zone1 not in self.zones or zone2 not in self.zones:
            raise ParsingError(f"Connection references an undefined zone ({zone1} or {zone2}).", line_number)

        link: Tuple[str, str] = (min(zone1, zone2), max(zone1, zone2))
        if link in self._parsed_links:
            raise ParsingError("Duplicate connection.", line_number)
        self._parsed_links.add(link)

        metadata = self._extract_metadata(meta_str, line_number)
        
        try:
            max_link_capacity = int(metadata.get("max_link_capacity", 1))
        except ValueError:
            raise ParsingError("max_link_capacity must be an integer.", line_number)
            
        if max_link_capacity <= 0:
            raise ParsingError("max_link_capacity must be a positive integer.", line_number)

        connection = Connection(
            zone1=zone1,
            zone2=zone2,
            max_link_capacity=max_link_capacity
        )
        self.connections.append(connection)

    def _extract_metadata(self, meta_str: Optional[str], line_number: int) -> Dict[str, str]:
        """Convertit la chaîne de métadonnées optionnelles en dictionnaire."""
        metadata: Dict[str, str] = {}
        if not meta_str:
            return metadata
        
        tokens = meta_str.split()
        for token in tokens:
            if '=' not in token:
                raise ParsingError(f"Invalid metadata format: {token}", line_number)
            key, value = token.split('=', 1)
            metadata[key] = value
            
        return metadata

    def _validate_graph(self) -> None:
        """Vérifie l'intégrité finale du fichier après lecture complète."""
        if not self.start_hub:
            raise Exception("Graph validation failed: Missing start_hub.")
        if not self.end_hub:
            raise Exception("Graph validation failed: Missing end_hub.")
        if self.nb_drones <= 0:
            raise Exception("Graph validation failed: nb_drones not defined or invalid.")


def parse_map_file(filepath: str) -> Tuple[NetworkGraph, Simulator]:
    """Parse le fichier de carte et retourne les instances de NetworkGraph et Simulator."""
    parser = GraphParser(filepath)
    parser.parse()

    if not parser.start_hub or not parser.end_hub:
        raise ValueError("Start hub and End hub must be defined.")

    # Passage des paramètres exacts attendus par NetworkGraph.__init__(zones, connections)
    graph = NetworkGraph(
        zones=parser.zones,
        connections=parser.connections
    )
    pathfinder = Pathfinder(graph, parser.start_hub, parser.end_hub)
    paths = pathfinder.find_multiple_disjoint_paths()
    simulator = Simulator(
        graph=graph,
        nb_drones=parser.nb_drones,
        start_hub=parser.start_hub,
        end_hub=parser.end_hub,
         paths=paths 
    )

    return graph, simulator