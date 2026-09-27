from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

@dataclass
class Zone:
    name:str
    x:int
    y:int
    zone_type:str = "normal"
    color: Optional[str] = None
    max_drones: int = 1
    current_drones: Set[str] = field(default_factory=set)

@dataclass
class Connection:
    zone1:str
    zone2:str
    max_link_capacity:int = 1
    current_traversals: int = 0

@dataclass
class Drone:
    id:str
    current_locatioon:str
    path:List[str] = field(default_factory=list)
    status:str = "waiting"