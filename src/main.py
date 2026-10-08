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
    parser.add_argument(
        "map_file",
        type=str,
        help="Chemin vers le fichier de carte à parser.",
    )
    parser.add_argument(
        "--3d",
        dest="three_d",
        action="store_true",
        help="Lance la visualisation 3D interactive avec Raylib.",
    )
    args = parser.parse_args()

    try:
        print("--- [1/3] Parsing ---")
        print(f"Lecture de : {args.map_file}")
        graph_parser = GraphParser(args.map_file)
        graph_parser.parse()
        print("✓ Carte chargée avec succès !")
    except ParsingError as error:
        exit_error(f"Erreur de syntaxe :\n{error}")
    except FileNotFoundError:
        exit_error(f"Fichier introuvable : {args.map_file}")
    except Exception as error:
        exit_error(f"Erreur inattendue :\n{error}")

    if not graph_parser.start_hub or not graph_parser.end_hub:
        exit_error("Erreur critique : start_hub ou end_hub manquant.")

    print("\n--- [2/3] Graphe ---")
    network = NetworkGraph(graph_parser.zones, graph_parser.connections)
    print(
        f"✓ Réseau construit ({len(network.zones)} zones, "
        f"{len(network.connections_list)} connexions)"
    )

    print("\n--- [3/3] Pathfinding Multi-chemins ---")
    pathfinder = Pathfinder(
        network, graph_parser.start_hub, graph_parser.end_hub
    )
    paths = pathfinder.find_multiple_disjoint_paths()

    if not paths:
        exit_error("Aucun chemin possible vers la destination !")

    print(f"✓ {len(paths)} chemin(s) indépendant(s) trouvé(s) :")
    for index, path in enumerate(paths, 1):
        print(f"  Chemin {index}: {' -> '.join(path)}")
    print()

    try:
        simulator = Simulator(
            graph=network,
            start_hub=graph_parser.start_hub,
            end_hub=graph_parser.end_hub,
            nb_drones=graph_parser.nb_drones,
            paths=paths,
        )
    except ValueError as error:
        exit_error(f"Configuration de simulation invalide : {error}")

    if args.three_d:
        print("--- Lancement de la visualisation 3D Raylib ---")
        try:
            from visualizer_3d import Visualizer3D

            visualizer = Visualizer3D(network, simulator)
            visualizer.run()
        except ImportError as error:
            exit_error(f"Erreur d'importation du visualiseur : {error}")
    else:
        print("--- Début de la simulation ---")
        completed = simulator.run()
        if completed:
            print(f"--- Simulation terminée en {simulator.turn} tours ---")
        else:
            exit_error(
                simulator.error
                or f"Simulation interrompue au tour {simulator.turn}."
            )


def exit_error(message: str) -> NoReturn:
    """Affiche une erreur puis quitte le programme avec un code non nul."""
    print(message, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()