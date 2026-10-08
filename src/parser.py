import re
from typing import Dict, List, Optional, Set, Tuple

from graph import NetworkGraph
from models import Connection, Zone
from pathfinder import Pathfinder
from simulation import Simulator


class ParsingError(Exception):
    """Erreur liée à la syntaxe ou aux métadonnées d'une carte."""

    def __init__(self, message: str, line_number: int) -> None:
        super().__init__(f"Error line {line_number}: {message}")


class GraphParser:
    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.nb_drones = 0
        self.zones: Dict[str, Zone] = {}
        self.connections: List[Connection] = []
        self.start_hub: Optional[str] = None
        self.end_hub: Optional[str] = None
        self._parsed_links: Set[Tuple[str, str]] = set()
        self._seen_nb_drones = False

    def parse(self) -> None:
        """Lit le fichier de carte puis vérifie son intégrité."""
        with open(self.filepath, "r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                clean_line = line.split("#", 1)[0].strip()
                if clean_line:
                    self._parse_line(clean_line, line_number)
        self._validate_graph()

    def _parse_line(self, line: str, line_number: int) -> None:
        if line.startswith("nb_drones:"):
            self._parse_nb_drones(line, line_number)
        elif (
            line.startswith("start_hub:")
            or line.startswith("end_hub:")
            or line.startswith("hub:")
        ):
            self._parse_hub(line, line_number)
        elif line.startswith("connection:"):
            self._parse_connection(line, line_number)
        else:
            raise ParsingError("Invalid syntax or unknown prefix.", line_number)

    def _parse_nb_drones(self, line: str, line_number: int) -> None:
        if self._seen_nb_drones:
            raise ParsingError("Multiple nb_drones definitions.", line_number)
        match = re.fullmatch(r"nb_drones:\s+(\d+)", line)
        if not match:
            raise ParsingError(
                "Invalid nb_drones format. Must be a positive integer.", line_number
            )
        count = int(match.group(1))
        if count <= 0:
            raise ParsingError("Number of drones must be greater than 0.", line_number)
        self.nb_drones = count
        self._seen_nb_drones = True

    def _parse_hub(self, line: str, line_number: int) -> None:
        pattern = (
            r"^(start_hub|end_hub|hub):\s+([^\s\-]+)\s+(-?\d+)\s+(-?\d+)"
            r"(?:\s+\[(.*?)\])?$"
        )
        match = re.fullmatch(pattern, line)
        if not match:
            raise ParsingError(
                "Invalid hub format or zone name contains dashes.", line_number
            )

        hub_type, name, x_str, y_str, meta_str = match.groups()
        if name in self.zones:
            raise ParsingError(f"Duplicate zone name: {name}", line_number)
        if hub_type == "start_hub" and self.start_hub is not None:
            raise ParsingError("Multiple start_hub defined.", line_number)
        if hub_type == "end_hub" and self.end_hub is not None:
            raise ParsingError("Multiple end_hub defined.", line_number)

        metadata = self._extract_metadata(
            meta_str, line_number, {"zone", "color", "max_drones"}
        )
        zone_type = metadata.get("zone", "normal")
        if zone_type not in {"normal", "blocked", "restricted", "priority"}:
            raise ParsingError(f"Invalid zone type: {zone_type}", line_number)
        if hub_type in {"start_hub", "end_hub"} and zone_type == "blocked":
            raise ParsingError(
                f"{hub_type} cannot use the blocked zone type.", line_number
            )

        try:
            max_drones = int(metadata.get("max_drones", "1"))
        except ValueError as error:
            raise ParsingError("max_drones must be an integer.", line_number) from error
        if max_drones <= 0:
            raise ParsingError("max_drones must be a positive integer.", line_number)

        zone = Zone(
            name=name,
            x=int(x_str),
            y=int(y_str),
            zone_type=zone_type,
            color=metadata.get("color"),
            max_drones=max_drones,
        )
        self.zones[name] = zone
        if hub_type == "start_hub":
            self.start_hub = name
        elif hub_type == "end_hub":
            self.end_hub = name

    def _parse_connection(self, line: str, line_number: int) -> None:
        pattern = r"^connection:\s+([^\s\-]+)-([^\s\-]+)(?:\s+\[(.*?)\])?$"
        match = re.fullmatch(pattern, line)
        if not match:
            raise ParsingError("Invalid connection format.", line_number)
        zone1, zone2, meta_str = match.groups()

        if zone1 == zone2:
            raise ParsingError("A connection cannot link a zone to itself.", line_number)
        if zone1 not in self.zones or zone2 not in self.zones:
            raise ParsingError(
                f"Connection references an undefined zone ({zone1} or {zone2}).",
                line_number,
            )

        link = (min(zone1, zone2), max(zone1, zone2))
        if link in self._parsed_links:
            raise ParsingError("Duplicate connection.", line_number)

        metadata = self._extract_metadata(
            meta_str, line_number, {"max_link_capacity"}
        )
        try:
            capacity = int(metadata.get("max_link_capacity", "1"))
        except ValueError as error:
            raise ParsingError(
                "max_link_capacity must be an integer.", line_number
            ) from error
        if capacity <= 0:
            raise ParsingError(
                "max_link_capacity must be a positive integer.", line_number
            )

        self._parsed_links.add(link)
        self.connections.append(Connection(zone1, zone2, capacity))

    def _extract_metadata(
        self,
        meta_str: Optional[str],
        line_number: int,
        allowed_keys: Set[str],
    ) -> Dict[str, str]:
        """Lit les métadonnées et refuse les clés inconnues ou répétées."""
        metadata: Dict[str, str] = {}
        if not meta_str:
            return metadata

        for token in meta_str.split():
            key, separator, value = token.partition("=")
            if not separator or not key or not value:
                raise ParsingError(f"Invalid metadata format: {token}", line_number)
            if key not in allowed_keys:
                raise ParsingError(f"Unknown metadata key: {key}", line_number)
            if key in metadata:
                raise ParsingError(f"Duplicate metadata key: {key}", line_number)
            metadata[key] = value
        return metadata

    def _validate_graph(self) -> None:
        if not self._seen_nb_drones or self.nb_drones <= 0:
            raise ValueError("Graph validation failed: nb_drones not defined or invalid.")
        if self.start_hub is None:
            raise ValueError("Graph validation failed: Missing start_hub.")
        if self.end_hub is None:
            raise ValueError("Graph validation failed: Missing end_hub.")
        if self.start_hub == self.end_hub:
            raise ValueError("Graph validation failed: hubs must be different.")


def parse_map_file(filepath: str) -> Tuple[NetworkGraph, Simulator]:
    """Parse une carte, calcule les chemins et prépare son simulateur."""
    parser = GraphParser(filepath)
    parser.parse()
    if parser.start_hub is None or parser.end_hub is None:
        raise ValueError("Start hub and end hub must be defined.")

    graph = NetworkGraph(zones=parser.zones, connections=parser.connections)
    pathfinder = Pathfinder(graph, parser.start_hub, parser.end_hub)
    paths = pathfinder.find_multiple_disjoint_paths()
    if not paths:
        raise ValueError(
            f"Aucun chemin valide entre '{parser.start_hub}' et '{parser.end_hub}'."
        )

    simulator = Simulator(
        graph=graph,
        nb_drones=parser.nb_drones,
        start_hub=parser.start_hub,
        end_hub=parser.end_hub,
        paths=paths,
    )
    return graph, simulator