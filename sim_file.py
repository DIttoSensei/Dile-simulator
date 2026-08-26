import re

RUN_RE = re.compile(r"^run\s+(\d+)\s+ticks$")
INJECT_RE = re.compile(
    r"^inject\s+(@\d+)\.([A-Za-z_][A-Za-z0-9_]*)\((.*)\)\s*->\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{\s*tick\s*:\s*(\d+)\s*\}$"
)
GRAPH_RE = re.compile(r"^graph\s+(on|off)$")


def parse_args(text):
    text = text.strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(",")]
    return [float(p) if "." in p else int(p) for p in parts]


def parse_sim_file(path):
    ticks = None
    schedule = {}
    graph = False

    with open(path) as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue

            m = RUN_RE.match(line)
            if m:
                ticks = int(m.group(1))
                continue

            m = INJECT_RE.match(line)
            if m:
                node_id, func_name, args_text, label, tick_str = m.groups()
                tick = int(tick_str)
                args = parse_args(args_text)
                schedule.setdefault(tick, []).append((node_id, func_name, args, label))
                continue

            m = GRAPH_RE.match(line)
            if m:
                graph = m.group(1) == "on"
                continue

            raise SyntaxError(f"{path}:{lineno}: unrecognized line: {line!r}")

    if ticks is None:
        raise SyntaxError(f"{path}: missing 'run <N> ticks' line")

    return ticks, schedule, graph