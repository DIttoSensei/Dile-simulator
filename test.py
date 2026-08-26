from blocks import load_folder, show

registry = load_folder("nodes")
for node_id, tree in registry.items():
    print(f"--- {node_id} ---")
    show([tree])