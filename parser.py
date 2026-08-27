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
        if kind == "NODEID":
            # @<id>.<attr> -- read another node's dile or a state var
            dot_kind, dot_val = self.next()
            if dot_kind != "DOT":
                raise SyntaxError(f"Expected '.' after node reference {val!r}")
            name_kind, name_val = self.next()
            if name_kind != "NAME":
                raise SyntaxError(f"Expected attribute name after '{val}.'")
            return ("nodeattr", val, name_val)
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
        self.tick_calls = []  # top-level call statements: run every tick, before decay
        self.id = node_id
        self.name = name
        self.base_dile = 0
        self.state = {}
        self.functions = {}
        self.has_decay = False

    def __repr__(self):
        return f"<node {self.id} {self.name} dile={self.base_dile} state={list(self.state)} fns={list(self.functions)}>"


# call target . func ( args ) -> label [optional {tick:N} or {tick:next}]
CALL_RE = re.compile(
    r"^(@\d+)\.([A-Za-z_][A-Za-z0-9_]*)\((.*)\)\s*->\s*([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*\{\s*tick\s*:\s*(\d+|next)\s*\})?$"
)
DECAY_RE = re.compile(r"^@bah_decay\(\)\s*->\s*tik$")
FUNC_HEADER_RE = re.compile(r"^@bah\s+([A-Za-z_][A-Za-z0-9_]*)\((.*?)\)\s*:$")
IF_HEADER_RE = re.compile(r"^IF\s*\{(.*)\}\s*:$")
ELIF_HEADER_RE = re.compile(r"^ELIF\s*\{(.*)\}\s*:$")
ELSE_HEADER_RE = re.compile(r"^ELSE\s*:$")
NODE_HEADER_RE = re.compile(r"^(@\d+)\s+node\s+([A-Za-z_][A-Za-z0-9_]*)\s*:$")
STATE_HEADER_RE = re.compile(r"^state:dile\s*=\s*(\d+(?:\.\d+)?)$")
VAR_LINE_RE = re.compile(r"^var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")


def _parse_call_stmt(m):
    target_id, func_name, args_text, label, tick_text = m.groups()
    args = [parse_expr(a) for a in split_args(args_text)]
    if tick_text is None:
        tick_num = None
    elif tick_text == "next":
        tick_num = "next"
    else:
        tick_num = int(tick_text)
    return ("call", target_id, func_name, args, label, tick_num)


def parse_statements(block_nodes):
    stmts = []
    i = 0
    n = len(block_nodes)
    while i < n:
        node = block_nodes[i]
        text = node["header"]

        m = IF_HEADER_RE.match(text)
        if m:
            branches = [(parse_expr(m.group(1)), parse_statements(node["children"]))]
            i += 1
            else_body = None
            while i < n:
                nxt_text = block_nodes[i]["header"]
                em = ELIF_HEADER_RE.match(nxt_text)
                if em:
                    branches.append((parse_expr(em.group(1)), parse_statements(block_nodes[i]["children"])))
                    i += 1
                    continue
                sm = ELSE_HEADER_RE.match(nxt_text)
                if sm:
                    else_body = parse_statements(block_nodes[i]["children"])
                    i += 1
                break
            stmts.append(("if_chain", branches, else_body))
            continue

        if ELIF_HEADER_RE.match(text) or ELSE_HEADER_RE.match(text):
            raise SyntaxError(f"{text!r} has no preceding IF")

        m = VAR_LINE_RE.match(text)
        if m:
            var_name, expr_text = m.groups()
            expr = parse_expr(expr_text.strip())
            stmts.append(("local_var", var_name, expr))
            i += 1
            continue

        m = CALL_RE.match(text)
        if m:
            stmts.append(_parse_call_stmt(m))
            i += 1
            continue

        if DECAY_RE.match(text):
            i += 1
            continue

        if "=" in text:
            var, expr_text = text.split("=", 1)
            var = var.strip()
            expr = parse_expr(expr_text.strip())
            stmts.append(("assign", var, expr))
            i += 1
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
            nd.tick_calls.append(_parse_call_stmt(m))
            continue

        raise SyntaxError(f"Unexpected line in node body: {text!r}")

    return nd