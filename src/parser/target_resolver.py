import re
from dataclasses import dataclass

from src.parser import document_registry
from src.parser.models import ViTri


@dataclass
class ResolvedTarget:
    document: str | None
    article: str | None
    clause: str | None
    point: str | None
    target_type: str = "STRUCTURAL"
    source_span: tuple[int, int] | None = None

    def as_vitri(self) -> ViTri:
        return ViTri(
            dieu=self.article,
            khoan=self.clause,
            diem=self.point,
            so_hieu_van_ban=self.document,
        )

    def to_canonical(self):
        return (self.document, self.article, self.clause, self.point, self.target_type)


@dataclass
class TargetSpec:
    document: str | None
    article: str | None
    clauses: list[str]
    points: list[str]
    source_span: tuple[int, int] | None = None


P_DIEM = re.compile(
    r"điểm\s+([a-zđ]\d*(?:\s*(?:,|và)\s*(?:điểm\s+)?[a-zđ]\d*)*)", re.IGNORECASE
)
P_KHOAN = re.compile(
    r"khoản\s+(\d+[a-zđ]?(?:\s*(?:,|và)\s*(?:khoản\s+)?\d+[a-zđ]?)*)", re.IGNORECASE
)
P_DIEU = re.compile(r"Điều\s+(\d+[a-zđ]?)", re.IGNORECASE)


def split_list(s: str) -> list[str]:
    values = []
    for x in re.split(r",|và", s):
        x = x.strip()
        # P_DIEM/P_KHOAN may capture repeated labels in lists such as
        # "điểm k, điểm l"; retain only the structural number/letter.
        x = re.sub(r"^(?:điểm|khoản|Điều)\s+", "", x, flags=re.IGNORECASE)
        if x:
            values.append(x)
    return values


def split_on_repeated_label(s: str, label: str) -> list[list[str]]:
    """Split a structural list when the larger-level label is repeated.

    In ``diem b khoan 4 va khoan 5``, the repeated ``khoan`` starts a new
    target group. This prevents the point from being broadcast to clause 5.
    An unlabeled continuation such as ``khoan 4 va 5`` remains one list.
    """
    label = P_KHOAN.pattern.split(r"\s+")[0]
    connector = r"(?:,|v\u00e0|ho\u1eb7c)"
    parts = re.split(
        rf"\s*{connector}\s*{re.escape(label)}\s+",
        s,
        flags=re.IGNORECASE,
    )
    return [values for part in parts if (values := split_list(part))]

    parts = re.split(
        rf"\s*(?:,|vÃ |hoáº·c)\s*{label}\s+",
        s,
        flags=re.IGNORECASE,
    )
    return [split_list(part) for part in parts if split_list(part)]


def resolve_targets(
    text: str, parent_context=None, default_document=None
) -> list[ResolvedTarget]:
    # 1. Detect explicit document
    explicit_doc = None
    van_ban_meta = document_registry.resolve(text)
    if van_ban_meta:
        explicit_doc = van_ban_meta["number"]

    doc_to_use = explicit_doc if explicit_doc else default_document

    # 2. Tokenize target components
    tokens = []
    for m in P_DIEM.finditer(text):
        tokens.append({"type": "DIEM", "span": m.span(), "text": m.group(1)})
    for m in P_KHOAN.finditer(text):
        tokens.append({"type": "KHOAN", "span": m.span(), "text": m.group(1)})
    for m in P_DIEU.finditer(text):
        tokens.append({"type": "DIEU", "span": m.span(), "text": m.group(1)})

    tokens.sort(key=lambda x: x["span"][0])

    if not tokens:
        return []

    # 3. Create TargetSpecs
    groups = []
    curr = TargetSpec(
        document=doc_to_use, article=None, clauses=[], points=[], source_span=None
    )
    span_start = tokens[0]["span"][0]

    for t in tokens:
        if t["type"] == "DIEM":
            if curr.clauses or curr.article:
                curr.source_span = (span_start, t["span"][0])
                groups.append(curr)
                curr = TargetSpec(
                    document=doc_to_use,
                    article=None,
                    clauses=[],
                    points=[],
                    source_span=None,
                )
                span_start = t["span"][0]
            curr.points.extend(split_list(t["text"]))
        elif t["type"] == "KHOAN":
            if curr.article:
                curr.source_span = (span_start, t["span"][0])
                groups.append(curr)
                curr = TargetSpec(
                    document=doc_to_use,
                    article=None,
                    clauses=[],
                    points=[],
                    source_span=None,
                )
                span_start = t["span"][0]
            elif curr.clauses:
                # A separately tokenized clause starts a new target group.
                # Smaller point context must not cross boundaries such as
                # ``diem a khoan 6; khoan 7``.
                curr.source_span = (span_start, t["span"][0])
                groups.append(curr)
                curr = TargetSpec(
                    document=doc_to_use,
                    article=None,
                    clauses=[],
                    points=[],
                    source_span=None,
                )
                span_start = t["span"][0]
            clause_groups = split_on_repeated_label(t["text"], "khoáº£n")
            curr.clauses.extend(clause_groups[0] if clause_groups else [])
            for clause_group in clause_groups[1:]:
                curr.source_span = (span_start, t["span"][0])
                groups.append(curr)
                curr = TargetSpec(
                    document=doc_to_use,
                    article=None,
                    clauses=clause_group,
                    points=[],
                    source_span=None,
                )
                span_start = t["span"][0]
        elif t["type"] == "DIEU":
            if curr.article:
                curr.source_span = (span_start, t["span"][0])
                groups.append(curr)
                curr = TargetSpec(
                    document=doc_to_use,
                    article=None,
                    clauses=[],
                    points=[],
                    source_span=None,
                )
                span_start = t["span"][0]
            curr.article = t["text"]
            curr.source_span = (span_start, t["span"][1])
            groups.append(curr)
            curr = TargetSpec(
                document=doc_to_use,
                article=None,
                clauses=[],
                points=[],
                source_span=None,
            )
            span_start = t["span"][1]

    if curr.points or curr.clauses or curr.article:
        curr.source_span = (span_start, len(text))
        groups.append(curr)

    # 4. Forward cascading for missing context
    for i in range(len(groups)):
        if not groups[i].article:
            for j in range(i + 1, len(groups)):
                if groups[j].article:
                    groups[i].article = groups[j].article
                    break
        if not groups[i].clauses and not groups[i].article:
            for j in range(i + 1, len(groups)):
                if groups[j].clauses:
                    groups[i].clauses = (
                        [groups[j].clauses[0]] if groups[j].clauses else []
                    )
                    break

    # 5. Expand TargetSpecs into ResolvedTarget list
    resolved = []
    for g in groups:
        if not g.article and not g.clauses and not g.points:
            continue

        articles = [g.article] if g.article else [None]
        clauses = g.clauses if g.clauses else [None]
        points = g.points if g.points else [None]

        for a in articles:
            for c in clauses:
                for p in points:
                    resolved.append(
                        ResolvedTarget(
                            document=g.document,
                            article=a,
                            clause=c,
                            point=p,
                            target_type="STRUCTURAL",
                            source_span=g.source_span,
                        )
                    )

    if parent_context:
        for r in resolved:
            if not r.article and parent_context.dieu:
                r.article = parent_context.dieu
            if not r.clause and parent_context.khoan:
                r.clause = parent_context.khoan
            # A point context cannot cross into an explicitly named larger
            # unit. Only a target with no structural identity may inherit it.
            if not r.point and not r.clause and not r.article and parent_context.diem:
                r.point = parent_context.diem

    return resolved
