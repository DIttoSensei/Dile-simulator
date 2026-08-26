import os


def build_indent_tree(source):
    """
    Turn one node file's source into a tree based on indentation.
    Stray '{' / '}' lines are decorative and get discarded --
    indentation alone determines nesting.
    """
    lines = []
    for raw in source.split("\n"):
        code = raw.split("#", 1)[0].rstrip()
        stripped = code.strip()
        if stripped == "" or stripped == "{" or stripped == "}":
            continue
        indent = len(code) - len(code.lstrip(" "))
        if stripped.endswith("{"):
            stripped = stripped[:-1].rstrip()
        lines.append((indent, stripped))

    root = {"header": None, "indent": -1, "children": []}
    stack = [root]

    for indent, text in lines:
        node = {"header": text, "indent": indent, "children": []}
        while stack[-1]["indent"] >= indent:
            stack.pop()
        stack[-1]["children"].append(node)
        stack.append(node)

    return root["children"]


def get_node_id(tree):
    header = tree[0]["header"]
    return header.split()[0]


def load_folder(folder_path, extension=".rd"):
    registry = {}
    for filename in sorted(os.listdir(folder_path)):
        if not filename.endswith(extension):
            continue
        path = os.path.join(folder_path, filename)
        with open(path) as f:
            source = f.read()
        tree = build_indent_tree(source)
        if len(tree) != 1:
            raise SyntaxError(f"{filename}: expected exactly one top-level node, found {len(tree)}")
        node_id = get_node_id(tree)
        if node_id in registry:
            raise SyntaxError(f"{filename}: duplicate node id {node_id}")
        registry[node_id] = tree[0]
    return registry


def show(blocks, depth=0):
    for b in blocks:
        print("  " * depth + f"HEADER: {b['header']}")
        show(b["children"], depth + 1)