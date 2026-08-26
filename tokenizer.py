import re

TOKEN_SPEC = [
    ("NUMBER",   r"\d+(\.\d+)?"),
    ("NODEID",   r"@\d+"),
    ("BAH",      r"@bah"),
    ("ARROW",    r"->"),
    ("EQEQ",     r"=="),
    ("NEQ",      r"!="),
    ("LE",       r"<="),
    ("GE",       r">="),
    ("OP",       r"[+\-*/<>=]"),
    ("LBRACE",   r"\{"),
    ("RBRACE",   r"\}"),
    ("LPAREN",   r"\("),
    ("RPAREN",   r"\)"),
    ("COLON",    r":"),
    ("COMMA",    r","),
    ("DOT",      r"\."),
    ("NAME",     r"[A-Za-z_][A-Za-z0-9_]*"),
    ("SKIP",     r"[ \t]+"),
]

MASTER_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC))

def tokenize(line):
    tokens = []
    pos = 0
    while pos < len(line):
        match = MASTER_RE.match(line, pos)
        if not match:
            raise SyntaxError(f"Unexpected character at {pos}: {line[pos:]!r}")
        kind = match.lastgroup
        value = match.group()
        if kind != "SKIP":
            tokens.append((kind, value))
        pos = match.end()
    return tokens


if __name__ == "__main__":
    test_lines = [
        "@1 node Amygdala:",
        "state:dile = 20 {",
        "var threshold = 70",
        "@bah receive_input(amount):",
        "IF {dile == threshold}:",
        "@5.trigger_stress_response(dile) -> once",
    ]
    for line in test_lines:
        print(line, "->", tokenize(line))