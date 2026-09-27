import sys
import argparse
from typing import NoReturn

# Importation de toutes nos briques depuis notre module local
from parser import GraphParser, ParsingError
from graph import NetworkGraph
from pathfinder import Pathfinder

def main() -> None:
    # 1. Configuration des arguments
    parser = argparse.ArgumentParser(
        description="Fly-in: Simulateur de routage de drones (Projet 42)."
    )
    parser.add_argument("map_file", type=str, help="Chemin vers le fichier de carte à parser.")
    args = parser.parse_args()

    # 2. Parsing du fichier
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

    # Vérification de sécurité pour le typage strict (mypy)
    if not graph_parser.start_hub or not graph_parser.end_hub:
        exit_error("Erreur critique : start_hub ou end_hub manquant.")

    # 3. Construction du Graphe
    print(f"\n--- [2/3] Graphe ---")
    network = NetworkGraph(graph_parser.zones, graph_parser.connections)
    print(f"✓ Réseau construit ({len(network.zones)} zones, {len(network.connections_list)} connexions)")

    # 4. Calcul du chemin (Pathfinding)
    print(f"\n--- [3/3] Pathfinding ---")
    pathfinder = Pathfinder(network, graph_parser.start_hub, graph_parser.end_hub)
    best_path = pathfinder.find_shortest_path()

    if best_path:
        print(f"✓ Chemin optimal trouvé : {' -> '.join(best_path)}")
        print(f"  Nombre d'étapes : {len(best_path)}")
    else:
        print("Aucun chemin possible vers la destination !")

def exit_error(message: str) -> NoReturn:
    """Affiche un message d'erreur et quitte le programme proprement."""
    print(message, file=sys.stderr)
    sys.exit(1)

if __name__ == '__main__':
    main()