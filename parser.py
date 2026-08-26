import re
from tokenizer import tokenize


class ExprParser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def parse(self):
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        kind, val = self.peek()
        if kind in ("EQEQ", "NEQ", "LE", "GE") or val in ("<", ">"):
            self.next()
            right = self.parse_additive()
            return ("binop", val, left, right)
        return left

    def parse_additive(self):
        left = self.parse_term()
        while self.peek()[1] in ("+", "-"):
            op = self.next()[1]
            right = self.parse_term()
            left = ("binop", op, left, right)
        return left

    def parse_term(self):
        left = self.parse_atom()
        while self.peek()[1] in ("*", "/"):
            op = self.next()[1]
            right = self.parse_atom()
            left = ("binop", op, left, right)
        return left

    def parse_atom(self):
        kind, val = self.next()
        if kind == "NUMBER":
            return ("num", float(val) if "." in val else int(val))
        if kind == "LPAREN":
            e = self.parse()
            self.next()
            return e
        if kind == "NAME":
            return ("var", val)
        raise SyntaxError(f"Unexpected token in expression: {val!r}")


def parse_expr(text):
    return ExprParser(tokenize(text)).parse()


def split_args(text):
    text = text.strip()
    return [p.strip() for p in text.split(",")] if text else []


class FunctionDef:
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body

    def __repr__(self):
        return f"<fn {self.name}({self.params})>"


class NodeDef:
    def __init__(self, node_id, name):
        self.tick_calls = []     # top-level call statements: run every tick, before decay
        self.id = node_id
        self.name = name
        self.base_dile = 0
        self.state = {}
        self.functions = {}
        self.has_decay = False

    def __repr__(self):
        return f"<node {self.id} {self.name} dile={self.base_dile} state={list(self.state)} fns={list(self.functions)}>"


CALL_RE = re.compile(r"^(@\d+)\.([A-Za-z_][A-Za-z0-9_]*)\((.*)\)\s*->\s*([A-Za-z_][A-Za-z0-9_]*)$")
DECAY_RE = re.compile(r"^@bah_decay\(\)\s*->\s*tik$")
FUNC_HEADER_RE = re.compile(r"^@bah\s+([A-Za-z_][A-Za-z0-9_]*)\((.*?)\)\s*:$")
IF_HEADER_RE = re.compile(r"^IF\s*\{(.*)\}\s*:$")
NODE_HEADER_RE = re.compile(r"^(@\d+)\s+node\s+([A-Za-z_][A-Za-z0-9_]*)\s*:$")
STATE_HEADER_RE = re.compile(r"^state:dile\s*=\s*(\d+(?:\.\d+)?)$")
VAR_LINE_RE = re.compile(r"^var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")


def parse_statements(block_nodes):
    stmts = []
    for node in block_nodes:
        text = node["header"]

        m = IF_HEADER_RE.match(text)
        if m:
            cond = parse_expr(m.group(1))
            body = parse_statements(node["children"])
            stmts.append(("if", cond, body))
            continue

        m = CALL_RE.match(text)
        if m:
            target_id, func_name, args_text, label = m.groups()
            args = [parse_expr(a) for a in split_args(args_text)]
            stmts.append(("call", target_id, func_name, args, label))
            continue

        if DECAY_RE.match(text):
            continue

        if "=" in text:
            var, expr_text = text.split("=", 1)
            var = var.strip()
            expr = parse_expr(expr_text.strip())
            stmts.append(("assign", var, expr))
            continue

        raise SyntaxError(f"Unrecognized statement: {text!r}")

    return stmts


def parse_function(fn_node):
    m = FUNC_HEADER_RE.match(fn_node["header"])
    if not m:
        raise SyntaxError(f"Bad function header: {fn_node['header']!r}")
    name, params_text = m.groups()
    params = [p.strip() for p in params_text.split(",") if p.strip()]
    body = parse_statements(fn_node["children"])
    return FunctionDef(name, params, body)


def parse_node(tree):
    m = NODE_HEADER_RE.match(tree["header"])
    if not m:
        raise SyntaxError(f"Bad node header: {tree['header']!r}")
    node_id, name = m.groups()
    nd = NodeDef(node_id, name)

    for child in tree["children"]:
        text = child["header"]

        m = STATE_HEADER_RE.match(text)
        if m:
            nd.base_dile = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
            for var_line in child["children"]:
                vm = VAR_LINE_RE.match(var_line["header"])
                if not vm:
                    raise SyntaxError(f"Bad var line: {var_line['header']!r}")
                var_name, val_text = vm.groups()
                nd.state[var_name] = parse_expr(val_text.strip())
            continue

        if FUNC_HEADER_RE.match(text):
            fn = parse_function(child)
            nd.functions[fn.name] = fn
            continue

        if DECAY_RE.match(text):
            nd.has_decay = True
            continue

        m = CALL_RE.match(text)
        if m:
            target_id, func_name, args_text, label = m.groups()
            args = [parse_expr(a) for a in split_args(args_text)]
            nd.tick_calls.append(("call", target_id, func_name, args, label))
            continue

        raise SyntaxError(f"Unexpected line in node body: {text!r}")

    return nd