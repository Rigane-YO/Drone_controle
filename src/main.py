import sys
import argparse
from typing import NoReturn

from parser import GraphParser, ParsingError
from graph import NetworkGraph
from pathfinder import Pathfinder
from simulation import Simulator

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fly-in: Simulateur de routage de drones (Projet 42)."
    )
    parser.add_argument("map_file", type=str, help="Chemin vers le fichier de carte à parser.")
    args = parser.parse_args()

    try:
        print(f"--- [1/3] Parsing ---")
        print(f"Lecture de : {args.map_file}")
        graph_parser = GraphParser(args.map_file)
        graph_parser.parse()
        print("✓ Carte chargée avec succès !")
    except ParsingError as e:
        exit_error(f"Erreur de syntaxe :\n{e}")
    except FileNotFoundError:
        exit_error(f"Fichier introuvable : {args.map_file}")
    except Exception as e:
        exit_error(f"Erreur inattendue :\n{e}")

    if not graph_parser.start_hub or not graph_parser.end_hub:
        exit_error("Erreur critique : start_hub ou end_hub manquant.")

    print(f"\n--- [2/3] Graphe ---")
    network = NetworkGraph(graph_parser.zones, graph_parser.connections)
    print(f"✓ Réseau construit ({len(network.zones)} zones, {len(network.connections_list)} connexions)")

    print(f"\n--- [3/3] Pathfinding Multi-chemins ---")
    pathfinder = Pathfinder(network, graph_parser.start_hub, graph_parser.end_hub)
    paths = pathfinder.find_multiple_disjoint_paths()

    if paths:
        print(f"✓ {len(paths)} chemin(s) indépendant(s) trouvé(s) :")
        for idx, p in enumerate(paths, 1):
            print(f"  Chemin {idx}: {' -> '.join(p)}")
        print()
        
        print("--- Début de la simulation ---")
        simulator = Simulator(
            graph=network,
            start_hub=graph_parser.start_hub,
            end_hub=graph_parser.end_hub,
            nb_drones=graph_parser.nb_drones,
            paths=paths
        )
        simulator.run()
        print(f"--- Simulation terminée en {simulator.turn} tours ---")
        
    else:
        print("Aucun chemin possible vers la destination !")

def exit_error(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(1)

if __name__ == '__main__':
    main()