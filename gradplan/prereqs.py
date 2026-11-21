"""Turn SOC ``preReqNotes`` text into a boolean expression tree.

Real strings from the API look like::

    (01:198:112 DATA STRUCTURES )<em> OR </em>(14:332:351 PROGRM METHODOLOGYII )
    ((01:198:205 ... or 14:332:312 ... ) and (01:640:152 CALCULUS II ...))<em> OR </em> (...)
    Any Course EQUAL or GREATER Than: (01:640:112 PRECALCULUS PART II )
    (14:332:231 DIGITAL LOGIC DESIGN ) AND (14:332:233 DIGITAL LOGIC DESIGN LAB )

Course titles are free text and can contain "AND"/"OR", so an operator only
counts when it is followed by a course code or an opening parenthesis. AND
binds tighter than OR. Anything the parser can't account for (stray words such
as "permission of instructor", unbalanced parentheses, a dangling operator) is
reported in ``ParseResult.flags`` so it can be fixed by hand in
``config/prereq_overrides.yaml``.

The same parser reads the override syntax, which is just codes, ``and``,
``or``, parentheses, ``coreq:CODE`` for a corequisite (same term is fine) and
``CODE+`` for "this course or any higher-numbered one in the subject".
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Union

from .codes import CODE_RE, number, subject

AT_LEAST_RE = re.compile(r"any\s+course\s+equal\s+or\s+greater\s+than\s*:?", re.I)
TOKEN_RE = re.compile(r"\(|\)|(?:coreq:)?\d{2}:\d{3}:\d{3}[A-Z]?\+?|[^\s()]+", re.I)
SUSPICIOUS_RE = re.compile(
    r"permission|consent|placement|corequisite|concurrent|standing|grade|credits?\b|equivalent|"
    r"approval|department|instructor|majors?\b|minors?\b|exam|score|not open", re.I)


@dataclass(frozen=True)
class Leaf:
    code: str
    or_higher: bool = False     # "Any Course EQUAL or GREATER Than"
    coreq: bool = False         # may be taken in the same term


@dataclass
class Op:
    op: str                     # "and" | "or"
    children: list["Node"] = field(default_factory=list)


Node = Union[Leaf, Op, None]


@dataclass
class ParseResult:
    tree: Node
    raw: str = ""
    flags: list[str] = field(default_factory=list)
    source: str = "soc"         # "soc" | "override"

    @property
    def ok(self) -> bool:
        return not self.flags


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def _tokens(text: str, flags: list[str]) -> list[str]:
    at_least = bool(AT_LEAST_RE.search(text))
    text = AT_LEAST_RE.sub(" ", text)
    raw = TOKEN_RE.findall(text)
    out: list[str] = []
    stray: list[str] = []
    in_title = False
    for i, tok in enumerate(raw):
        low = tok.lower()
        bare = re.sub(r"(?i)^coreq:", "", tok).rstrip("+")
        if tok in "()":
            out.append(tok)
            in_title = False
        elif CODE_RE.fullmatch(bare):
            out.append(("@" if at_least else "") + tok)
            in_title = True
        elif low in ("and", "or", "&&", "||"):
            nxt = raw[i + 1] if i + 1 < len(raw) else ""
            nbare = re.sub(r"(?i)^coreq:", "", nxt).rstrip("+")
            if nxt == "(" or CODE_RE.fullmatch(nbare):
                out.append("and" if low in ("and", "&&") else "or")
                in_title = False
            elif not in_title:
                stray.append(tok)
        elif not in_title:
            stray.append(tok)
        elif SUSPICIOUS_RE.search(tok):
            # words like "permission" hiding inside what looks like a title
            stray.append(tok)
    if stray:
        flags.append("unrecognized text: " + " ".join(stray)[:120])
    return out


class _Parser:
    def __init__(self, tokens: list[str], flags: list[str]):
        self.t, self.i, self.flags = tokens, 0, flags

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse_or(self) -> Node:
        items = [self.parse_and()]
        while self.peek() == "or":
            self.take()
            items.append(self.parse_and())
        return _make("or", items)

    def parse_and(self) -> Node:
        items = [self.parse_atom()]
        while self.peek() == "and":
            self.take()
            items.append(self.parse_atom())
        return _make("and", items)

    def parse_atom(self) -> Node:
        tok = self.take()
        if tok == "(":
            node = self.parse_or()
            if self.peek() == ")":
                self.take()
            else:
                self.flags.append("unbalanced parentheses")
            return node
        if tok is None:
            self.flags.append("expression ends early (dangling and/or)")
            return None
        if tok in ("and", "or", ")"):
            self.flags.append(f"unexpected '{tok}'")
            return None
        at_least = tok.startswith("@")
        tok = tok.lstrip("@")
        coreq = tok.lower().startswith("coreq:")
        tok = re.sub(r"(?i)^coreq:", "", tok)
        plus = tok.endswith("+")
        return Leaf(tok.rstrip("+"), or_higher=at_least or plus, coreq=coreq)


def _make(op: str, items: list[Node]) -> Node:
    flat: list[Node] = []
    seen: set[Leaf] = set()
    for it in items:
        if it is None:
            continue
        if isinstance(it, Op) and it.op == op:
            for ch in it.children:
                if isinstance(ch, Leaf):
                    if ch in seen:
                        continue
                    seen.add(ch)
                flat.append(ch)
        elif isinstance(it, Leaf):
            if it not in seen:          # the SOC repeats codes ("331 and 331")
                seen.add(it)
                flat.append(it)
        else:
            flat.append(it)
    if not flat:
        return None
    if len(flat) == 1:
        return flat[0]
    return Op(op, flat)


def parse(text: str, source: str = "soc") -> ParseResult:
    cleaned = _clean(text)
    flags: list[str] = []
    if not cleaned or cleaned.lower() in ("none", "-"):
        return ParseResult(None, cleaned, [], source)
    tokens = _tokens(cleaned, flags)
    if not tokens:
        flags.append("no course codes found")
        return ParseResult(None, cleaned, flags, source)
    p = _Parser(tokens, flags)
    tree = p.parse_or()
    while p.peek() is not None:     # leftovers, e.g. an extra ')'
        extra = p.take()
        flags.append(f"unexpected '{extra}'")
        if extra in ("and", "or"):
            rest = p.parse_or()
            tree = _make(extra, [tree, rest])
    return ParseResult(simplify(tree), cleaned, sorted(set(flags)), source)


def simplify(node: Node) -> Node:
    """Absorption: (A) OR (A AND B) -> A. The SOC lists many redundant alternatives."""
    if node is None or isinstance(node, Leaf):
        return node
    kids = [simplify(c) for c in node.children]
    node = _make(node.op, kids)
    if not isinstance(node, Op):
        return node
    if node.op == "or":
        sets = [frozenset(_and_terms(c)) for c in node.children]
        keep = []
        for i, c in enumerate(node.children):
            if any(j != i and sets[j] < sets[i] for j in range(len(sets))):
                continue
            keep.append(c)
        return _make("or", keep)
    return node


def _and_terms(node: Node) -> list:
    if isinstance(node, Op) and node.op == "and":
        return [repr(c) for c in node.children]
    return [repr(node)]


def map_codes(node: Node, fn: Callable[[str], str]) -> Node:
    if node is None:
        return None
    if isinstance(node, Leaf):
        return Leaf(fn(node.code), node.or_higher, node.coreq)
    return simplify(_make(node.op, [map_codes(c, fn) for c in node.children]))


def leaves(node: Node) -> list[Leaf]:
    if node is None:
        return []
    if isinstance(node, Leaf):
        return [node]
    out: list[Leaf] = []
    for c in node.children:
        out.extend(leaves(c))
    return out


def codes(node: Node) -> set[str]:
    return {lf.code for lf in leaves(node)}


def leaf_ok(lf: Leaf, done: set[str]) -> bool:
    if lf.code in done:
        return True
    if lf.or_higher:
        subj, n = subject(lf.code), number(lf.code)
        return any(subject(t) == subj and number(t) >= n for t in done)
    return False


def satisfied(node: Node, done: Iterable[str], same_term: Iterable[str] = ()) -> bool:
    """Is the tree satisfied by courses finished earlier (``done``)? Corequisites may also
    be met by courses in ``same_term``."""
    done = set(done)
    now = done | set(same_term)

    def ev(n: Node) -> bool:
        if n is None:
            return True
        if isinstance(n, Leaf):
            return leaf_ok(n, now if n.coreq else done)
        res = [ev(c) for c in n.children]
        return all(res) if n.op == "and" else any(res)

    return ev(node)


def to_text(node: Node) -> str:
    if node is None:
        return "none"
    if isinstance(node, Leaf):
        return ("coreq:" if node.coreq else "") + node.code + ("+" if node.or_higher else "")
    return f" {node.op.upper()} ".join(
        to_text(c) if isinstance(c, Leaf) else f"({to_text(c)})" for c in node.children)
