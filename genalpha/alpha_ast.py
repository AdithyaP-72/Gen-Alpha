"""
FASTEXPR expression trees: parser, serializer, and typed node-level mutations.

Replaces string-based mutation (which corrupted field names containing operator
substrings and could not do crossover). Mutating typed nodes makes invalid
mutations unrepresentable:
  - operator swaps only happen at call nodes, constrained by arity
  - window changes only happen at numeric literals in time-series calls
  - field substitution respects category and MATRIX/VECTOR type
  - subtree crossover recombines two parents' call subtrees

Grammar (covers everything in the current template bank and history):
  program := stmt (';' stmt)* [';']
  stmt    := IDENT '=' expr | expr
  expr    := ternary
  ternary := or ('?' expr ':' expr)?
  or      := and ('||' and)*
  and     := cmp ('&&' cmp)*
  cmp     := add (('<'|'>'|'<='|'>='|'=='|'!=') add)*
  add     := mul (('+'|'-') mul)*
  mul     := unary (('*'|'/') unary)*
  unary   := ('-'|'!') unary | primary
  primary := NUMBER | IDENT ['(' expr (',' expr)* ')'] | '(' expr ')'

AST nodes are plain JSON-serializable dicts (stored in candidates.ast_json).
"""

import json
import random
import re
from pathlib import Path


class ParseError(ValueError):
    pass


# ─── Tokenizer ────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"""
    (?P<num>\d+\.\d*|\.\d+|\d+)
  | (?P<str>"[^"]*"|'[^']*')
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|==|!=|\|\||&&|[-+*/(),?:;=<>!])
  | (?P<ws>\s+)
""", re.VERBOSE)


def _tokenize(text):
    tokens = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise ParseError(f"Unexpected character {text[pos]!r} at position {pos}")
        pos = m.end()
        if m.lastgroup == "ws":
            continue
        tokens.append((m.lastgroup, m.group()))
    return tokens


# ─── Parser ───────────────────────────────────────────────────────
class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, value):
        kind, val = self.next()
        if val != value:
            raise ParseError(f"Expected {value!r}, got {val!r}")
        return val

    def parse_program(self):
        stmts = [self.parse_stmt()]
        while self.peek()[1] == ";":
            self.next()
            if self.peek()[0] is None:  # trailing semicolon
                break
            stmts.append(self.parse_stmt())
        if self.peek()[0] is not None:
            raise ParseError(f"Trailing input at token {self.peek()[1]!r}")
        if len(stmts) == 1 and stmts[0]["t"] != "assign":
            return stmts[0]
        return {"t": "prog", "stmts": stmts}

    def parse_stmt(self):
        # lookahead: IDENT '=' (but not '==')
        if (self.peek()[0] == "id"
                and self.i + 1 < len(self.tokens)
                and self.tokens[self.i + 1][1] == "="):
            name = self.next()[1]
            self.next()  # '='
            return {"t": "assign", "name": name, "x": self.parse_expr()}
        return self.parse_expr()

    def parse_expr(self):
        return self.parse_ternary()

    def parse_ternary(self):
        cond = self.parse_or()
        if self.peek()[1] == "?":
            self.next()
            a = self.parse_expr()
            self.expect(":")
            b = self.parse_expr()
            return {"t": "tern", "c": cond, "a": a, "b": b}
        return cond

    def _binary(self, sub, ops):
        node = sub()
        while self.peek()[1] in ops:
            op = self.next()[1]
            node = {"t": "bin", "op": op, "l": node, "r": sub()}
        return node

    def parse_or(self):
        return self._binary(self.parse_and, {"||"})

    def parse_and(self):
        return self._binary(self.parse_cmp, {"&&"})

    def parse_cmp(self):
        return self._binary(self.parse_add, {"<", ">", "<=", ">=", "==", "!="})

    def parse_add(self):
        return self._binary(self.parse_mul, {"+", "-"})

    def parse_mul(self):
        return self._binary(self.parse_unary, {"*", "/"})

    def parse_unary(self):
        if self.peek()[1] in ("-", "!"):
            op = self.next()[1]
            return {"t": "un", "op": op, "x": self.parse_unary()}
        return self.parse_primary()

    def parse_primary(self):
        kind, val = self.next()
        if kind == "num":
            return {"t": "num", "v": float(val) if "." in val else int(val)}
        if kind == "id":
            if self.peek()[1] == "(":
                self.next()
                args = []
                if self.peek()[1] != ")":
                    args.append(self.parse_arg())
                    while self.peek()[1] == ",":
                        self.next()
                        args.append(self.parse_arg())
                self.expect(")")
                return {"t": "call", "name": val, "args": args}
            return {"t": "id", "name": val}
        if kind == "str":
            return {"t": "str", "v": val[1:-1]}
        if val == "(":
            node = self.parse_expr()
            self.expect(")")
            return node
        raise ParseError(f"Unexpected token {val!r}")

    def parse_arg(self):
        # keyword argument: IDENT '=' expr (but not '==')
        if (self.peek()[0] == "id"
                and self.i + 1 < len(self.tokens)
                and self.tokens[self.i + 1][1] == "="):
            name = self.next()[1]
            self.next()  # '='
            return {"t": "kw", "name": name, "x": self.parse_expr()}
        return self.parse_expr()


def parse(expression):
    """Parse a FASTEXPR string into an AST dict. Raises ParseError."""
    tokens = _tokenize(expression)
    if not tokens:
        raise ParseError("Empty expression")
    return _Parser(tokens).parse_program()


# ─── Serializer (precedence-aware) ────────────────────────────────
_PREC = {"?": 1, "||": 2, "&&": 3,
         "<": 4, ">": 4, "<=": 4, ">=": 4, "==": 4, "!=": 4,
         "+": 5, "-": 5, "*": 6, "/": 6}
_UNARY_PREC = 7


def _prec(node):
    if node["t"] == "bin":
        return _PREC[node["op"]]
    if node["t"] == "un":
        return _UNARY_PREC
    if node["t"] == "tern":
        return _PREC["?"]
    return 99


def to_string(node):
    t = node["t"]
    if t == "prog":
        return "; ".join(to_string(s) for s in node["stmts"])
    if t == "assign":
        return f"{node['name']} = {to_string(node['x'])}"
    if t == "num":
        v = node["v"]
        return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
    if t == "str":
        return f'"{node["v"]}"'
    if t == "kw":
        return f"{node['name']}={to_string(node['x'])}"
    if t == "id":
        return node["name"]
    if t == "call":
        return f"{node['name']}({', '.join(to_string(a) for a in node['args'])})"
    if t == "un":
        inner = to_string(node["x"])
        if _prec(node["x"]) < _UNARY_PREC:
            inner = f"({inner})"
        return f"{node['op']}{inner}"
    if t == "bin":
        my = _PREC[node["op"]]
        left = to_string(node["l"])
        right = to_string(node["r"])
        if _prec(node["l"]) < my:
            left = f"({left})"
        # right side: parenthesize at <= for non-associative safety on -, /
        if _prec(node["r"]) < my or (_prec(node["r"]) == my and node["op"] in ("-", "/")):
            right = f"({right})"
        return f"{left} {node['op']} {right}"
    if t == "tern":
        c, a, b = (to_string(node[k]) for k in ("c", "a", "b"))
        return f"{c} ? {a} : {b}"
    raise ValueError(f"Unknown node type {t}")


def clone(node):
    return json.loads(json.dumps(node))


def walk(node):
    """Yield every node in the tree (pre-order)."""
    yield node
    t = node["t"]
    if t == "prog":
        for s in node["stmts"]:
            yield from walk(s)
    elif t in ("assign", "kw"):
        yield from walk(node["x"])
    elif t == "call":
        for a in node["args"]:
            yield from walk(a)
    elif t == "un":
        yield from walk(node["x"])
    elif t == "bin":
        yield from walk(node["l"])
        yield from walk(node["r"])
    elif t == "tern":
        for k in ("c", "a", "b"):
            yield from walk(node[k])


# ─── Operator signatures from brain_operators.json ────────────────
def _load_operator_arities():
    from genalpha.config import BRAIN_OPERATORS as path
    arities = {}
    if path.exists():
        with open(path) as f:
            for op in json.load(f):
                definition = op.get("definition", "")
                m = re.match(r"[\w]+\((.*)\)", definition)
                if m:
                    inner = m.group(1).strip()
                    # optional args (e.g. "x, d, k=2") count as minimum arity too
                    required = [a for a in inner.split(",") if a and "=" not in a]
                    arities[op["name"]] = (len(required), inner.count(",") + 1 if inner else 0)
    return arities


OPERATOR_ARITIES = _load_operator_arities()

# Semantically interchangeable families (same input/output shape)
_SWAP_FAMILIES = [
    {"ts_rank", "ts_zscore", "ts_quantile", "ts_av_diff"},
    {"ts_mean", "ts_median", "ts_sum"},
    {"ts_max", "ts_min"},
    {"rank", "zscore"},
    {"group_rank", "group_zscore"},
    {"vec_avg", "vec_sum", "vec_max"},
]

_WINDOW_LADDER = [5, 10, 20, 63, 126, 252, 500]


def _arity_ok(name, nargs):
    if name not in OPERATOR_ARITIES:
        return True  # unknown operator — let the validator decide
    lo, hi = OPERATOR_ARITIES[name]
    return lo <= nargs <= max(lo, hi)


# ─── Typed mutations ──────────────────────────────────────────────
def mutate_operator_swap(tree):
    """Swap one call node's operator for a same-family, arity-compatible one."""
    out = []
    calls = [n for n in walk(tree) if n["t"] == "call"]
    for family in _SWAP_FAMILIES:
        for call in calls:
            if call["name"] in family:
                for alt in sorted(family - {call["name"]}):
                    if not _arity_ok(alt, len(call["args"])):
                        continue
                    mutated = clone(tree)
                    # find the same call node in the clone by position
                    for orig, cl in zip(walk(tree), walk(mutated)):
                        if orig is call:
                            cl["name"] = alt
                            break
                    out.append((mutated, f"op_{call['name']}_to_{alt}"))
    return out


def mutate_windows(tree):
    """Perturb the lookback constant of time-series calls through the ladder."""
    out = []
    for node in walk(tree):
        if node["t"] == "call" and node["name"].startswith("ts_") and len(node["args"]) >= 2:
            win_arg = node["args"][-1]
            if win_arg["t"] == "num" and win_arg["v"] in _WINDOW_LADDER:
                idx = _WINDOW_LADDER.index(win_arg["v"])
                for new_idx in (idx - 1, idx + 1):
                    if 0 <= new_idx < len(_WINDOW_LADDER):
                        mutated = clone(tree)
                        for orig, cl in zip(walk(tree), walk(mutated)):
                            if orig is win_arg:
                                cl["v"] = _WINDOW_LADDER[new_idx]
                                break
                        out.append((mutated, f"window_{win_arg['v']}_to_{_WINDOW_LADDER[new_idx]}"))
    return out


def mutate_field_substitution(tree, field_index, categorize, max_subs=2):
    """Swap a data-field identifier for another of the same category and type."""
    out = []
    id_nodes = [n for n in walk(tree) if n["t"] == "id" and n["name"] in field_index]
    for node in id_nodes:
        meta = field_index[node["name"]]
        cat = categorize(node["name"], meta)
        ftype = meta.get("type")
        same_family = [fid for fid, m in field_index.items()
                       if fid != node["name"]
                       and m.get("type") == ftype
                       and m.get("coverage", 0) > 0.2
                       and categorize(fid, m) == cat]
        random.shuffle(same_family)
        for fid in same_family[:max_subs]:
            mutated = clone(tree)
            for orig, cl in zip(walk(tree), walk(mutated)):
                if orig is node:
                    cl["name"] = fid
                    break
            out.append((mutated, f"field_{node['name']}_to_{fid}"))
    return out


def mutate_golden_wrap(tree):
    """Wrap the whole expression (last statement) in group_rank(..., subindustry)."""
    if any(n["t"] == "call" and n["name"].startswith("group_") for n in walk(tree)):
        return []
    if tree["t"] == "prog":
        mutated = clone(tree)
        last = mutated["stmts"][-1]
        if last["t"] == "assign":
            return []
        mutated["stmts"][-1] = {"t": "call", "name": "group_rank",
                                "args": [last, {"t": "id", "name": "subindustry"}]}
        return [(mutated, "golden_combo_wrap")]
    mutated = {"t": "call", "name": "group_rank",
               "args": [clone(tree), {"t": "id", "name": "subindustry"}]}
    return [(mutated, "golden_combo_wrap")]


def crossover(tree_a, tree_b, attempts=4):
    """Subtree crossover: replace a random call subtree of A with one from B."""
    calls_a = [n for n in walk(tree_a) if n["t"] == "call"]
    calls_b = [n for n in walk(tree_b) if n["t"] == "call"]
    if not calls_a or not calls_b:
        return []
    out = []
    for _ in range(attempts):
        target = random.choice(calls_a)
        donor = random.choice(calls_b)
        if to_string(target) == to_string(donor):
            continue
        mutated = clone(tree_a)
        for orig, cl in zip(walk(tree_a), walk(mutated)):
            if orig is target:
                cl.clear()
                cl.update(clone(donor))
                break
        out.append((mutated, f"crossover_{donor['name']}"))
    return out


def generate_ast_mutations(expression, field_index=None, categorize=None, crossover_parent=None):
    """All typed mutations of an expression. Returns [(expression_str, mutation_name)].

    Returns [] when the expression doesn't parse — callers fall back to
    settings-only mutations.
    """
    try:
        tree = parse(expression)
    except ParseError:
        return []

    results = []
    results.extend(mutate_operator_swap(tree))
    results.extend(mutate_windows(tree))
    results.extend(mutate_golden_wrap(tree))
    if field_index and categorize:
        results.extend(mutate_field_substitution(tree, field_index, categorize))
    if crossover_parent:
        try:
            other = parse(crossover_parent)
            results.extend(crossover(tree, other))
        except ParseError:
            pass

    seen = set()
    out = []
    for mutated, name in results:
        try:
            s = to_string(mutated)
        except ValueError:
            continue
        if s != expression and s not in seen:
            seen.add(s)
            out.append((s, name))
    return out


def generalize_to_template(expression, field_index):
    """Replace data-field identifiers with {FIELD} slots for the template bank."""
    try:
        tree = parse(expression)
    except ParseError:
        return None
    replaced = 0
    for node in walk(tree):
        if node["t"] == "id" and node["name"] in field_index:
            node["name"] = "{FIELD}"
            replaced += 1
    if replaced == 0:
        return None
    return to_string(tree)
