import sys
import argparse
from typing import NoReturn
from parser import GraphParser, ParsingError

def main() -> None:
    parser = argparse.ArgumentParser(
        description= "Fly-in: Simulateur de routage de drones (Projet 42)."
    )
    parser.add_argument(
        "map_file", 
        type=str, 
        help="Chemin vers le fichier de carte à parser."
    )
    args = parser.parse_args()
    try:
        print(f"chargement de la carte depuis: {args.map_file}...")
        graph_parser = GraphParser(args.map_file)
        graph_parser.parse()
        print(f"✓ Carte chargée avec succès !")
        print(f"  - Nombre de drones : {graph_parser.nb_drones}")
        print(f"  - Point de départ  : {graph_parser.start_hub}")
        print(f"  - Point d'arrivée  : {graph_parser.end_hub}")
        print(f"  - Nombre de zones  : {len(graph_parser.zones)}")
        print(f"  - Connexions       : {len(graph_parser.connections)}")

    except ParsingError as e:
        print(f"\n Erreur de syntaxe dans le fichier :\n{e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"\n Erreur : Le fichier '{args.map_file}' est introuvable.")
        sys.exit(1)
    except Exception as e:
        print(f"\n Erreur inattendue :\n{e}")
        sys.exit(1)

    # 3. (À venir) Calcul du pathfinding
    # ...

    # 4. (À venir) Exécution de la simulation tour par tour
    # ...

def exit_error(message: str) -> NoReturn:
    """Affiche un message d'erreur et quitte le programme proprement."""
    print(message, file=sys.stderr)
    sys.exit(1)

if __name__ == '__main__':
    main()