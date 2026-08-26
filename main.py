import argparse
from blocks import load_folder
from parser import parse_node
import webbrowser
from sim_file import parse_sim_file
import os
from graph import generate_svg_graph
from interpreter import Simulator


def load_simulator(folder):
    trees = load_folder(folder)
    node_defs = {node_id: parse_node(tree) for node_id, tree in trees.items()}
    return Simulator(node_defs)


def main():
    ap = argparse.ArgumentParser(
        prog="dile", 
        description="Dile Simulator - Created by Corvus.Q"
    )
    sub = ap.add_subparsers(dest="command", required=False)

    run_cmd = sub.add_parser("run", help="Run a simulation over a folder or a .sm file")
    
    # Adding help="..." prevents blank entries in `dile run --help`
    run_cmd.add_argument("folder", nargs="?", default="nodes", help="Folder containing .rd node files (default: nodes)")
    run_cmd.add_argument("--ticks", type=int, default=15, help="Number of ticks to run (default: 15)")
    run_cmd.add_argument(
        "--inject", action="append", default=[],
        help="Inject call: tick:@id.func(args):label"
    )
    run_cmd.add_argument("--graph", action="store_true", help="Generate and open an SVG graph")
    run_cmd.add_argument("--sim", help="Path to a .sm simulation file (overrides --ticks/--inject/--graph)")

    args = ap.parse_args()

    # If no subcommand was provided (e.g. user double-clicked dile.exe or typed 'dile')
    if args.command is None:
        print("==================================================")
        print(" Dile Simulator v1.0.1")
        print(" Created by Corvus.Q")
        print(" GitHub: https://github.com/DIttoSensei/Dile-simulator")
        print("==================================================")
        print("\nUsage:")
        print("  dile run [folder]         Run node simulation (default: nodes)")
        print("  dile run --sim <file.sm>  Run a .sm simulation file")
        print("  dile run --help               Show all options and flags")
        
        # Pause execution if launched by double-clicking in File Explorer
        input("\nPress Enter to exit...")
        return


    if args.command == "run":
        sim = load_simulator(args.folder)

        if args.sim:
            ticks, schedule, want_graph = parse_sim_file(args.sim)
        else:
            ticks = args.ticks
            want_graph = args.graph
            schedule = {}
            for spec in args.inject:
                tick_str, rest = spec.split(":", 1)
                tick = int(tick_str)
                call_part, label = rest.rsplit(":", 1)
                node_id, remainder = call_part.split(".", 1)
                func_name, args_str = remainder.split("(", 1)
                args_str = args_str.rstrip(")")
                call_args = [float(a) if "." in a else int(a) for a in args_str.split(",") if a.strip()]
                schedule.setdefault(tick, []).append((node_id, func_name, call_args, label))

        log = sim.run(ticks, schedule)
        print("\n".join(log))

        if want_graph:
            path = generate_svg_graph(sim, "run_graph.html")
            full_path = os.path.abspath(path)
            print(f"\nGraph written to {full_path}")
            try:
                os.startfile(full_path)
            except Exception as e:
                print(f"Couldn't auto-open the graph ({e}). Open it manually: {full_path}")


if __name__ == "__main__":
    main()