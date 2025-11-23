import re
import xml.etree.ElementTree as ET

try:
    from .number_text_utils import int_to_kanji, normalize_num, normalize_separators
    from .structure_extract import extract_structure, render_article_plain
    from .text_utils import clean_text_display
except ImportError:  # script fallback
    from number_text_utils import int_to_kanji, normalize_num, normalize_separators
    from structure_extract import extract_structure, render_article_plain
    from text_utils import clean_text_display


def extract_query_numbers(query: str) -> list[str]:
    """Extract base article numbers from the query, tolerant of prefixes/suffixes."""
    q = normalize_separators(normalize_num(query))
    q = re.sub(r"[法第条]", "", q)
    q = q.replace("の", "-")
    numbers: list[str] = []
    for piece in re.split(r"[^0-9-]+", q):
        if not piece:
            continue
        m = re.match(r"(\d+)(?:-(\d+))?", piece)
        if m:
            numbers.append(m.group(1))
            continue
        numbers.extend(re.findall(r"\d+", piece))
    seen = set()
    deduped = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    return deduped


def parse_number_token(token: str) -> tuple[str | None, str | None]:
    """Parse a single token and return (base, branch) if it contains a number."""
    t = normalize_separators(normalize_num(token))
    stripped = re.sub(r"[法第条]", "", t)
    stripped = stripped.replace("の", "-")
    m = re.search(r"(\d+)(?:-(\d+))?", stripped)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def generate_number_terms(base: str, branch_hint: str | None = None) -> set[str]:
    """Generate related search terms for a given article number."""
    terms: set[str] = set()
    try:
        n_int = int(base)
    except ValueError:
        return terms
    kan = int_to_kanji(n_int)
    base_forms = {
        base,
        f"{base}条",
        f"第{base}条",
        f"{kan}",
        f"{kan}条",
        f"第{kan}条",
        f"法第{base}条",
        f"令第{base}条",
        f"法第{kan}条",
        f"令第{kan}条",
        f"第{base}条の",
        f"第{kan}条の",
        f"法第{base}条の",
        f"令第{base}条の",
    }
    terms.update(base_forms)

    branch_candidates: list[str] = []
    if branch_hint:
        branch_candidates.append(branch_hint)
    branch_candidates.extend([str(i) for i in range(1, 11)])

    for b in branch_candidates:
        try:
            b_int = int(b)
        except ValueError:
            continue
        b_kan = int_to_kanji(b_int)
        terms.update(
            {
                f"第{base}条の{b}",
                f"第{kan}条の{b}",
                f"第{base}条の{b_kan}",
                f"第{kan}条の{b_kan}",
                f"法第{base}条の{b}",
                f"令第{base}条の{b}",
            }
        )

    expanded = set()
    for t in terms:
        expanded.add(t)
        expanded.add(normalize_num(t))
    return {x for x in expanded if x}


def build_term_groups(query: str, article_mode: bool = False) -> list[set[str]]:
    """Split query into tokens and expand each into OR groups."""
    tokens = [tok for tok in re.split(r"\s+", query) if tok]
    groups: list[set[str]] = []
    for tok in tokens:
        base, branch = parse_number_token(tok)
        group: set[str] = set()
        tok_norm = normalize_separators(normalize_num(tok))
        if base and article_mode:
            for term in generate_number_terms(base, branch):
                if "条" in term:
                    group.add(term)
            if "条" in tok_norm:
                group.add(tok_norm)
        else:
            group.add(tok_norm)
            if base:
                group.update(generate_number_terms(base, branch))
        groups.append({g for g in group if g})
    return groups


def matches_group(raw_text: str, norm_text: str, terms: set[str]) -> bool:
    """Check whether any term in the group matches raw or normalized text."""
    for term in terms:
        if not term:
            continue
        norm_term = normalize_num(term)
        if term in raw_text or norm_term in raw_text:
            return True
        if term in norm_text or norm_term in norm_text:
            return True
    return False


def is_branch_mode(query: str) -> bool:
    return ("の" in query) or any(ch in query for ch in ("-", "ー", "－", "―", "‐", "‑", "–", "—", "〜", "～"))


def build_branch_patterns(base: str, branch: str) -> list[re.Pattern]:
    """Generate regex patterns that require 条の/条- style with exact branch (fullmatch only)."""
    try:
        base_k = int_to_kanji(int(base))
    except Exception:
        base_k = base
    try:
        branch_k = int_to_kanji(int(branch))
    except Exception:
        branch_k = branch

    prefixes = ["", "法", "令"]
    base_variants = [
        f"{base}",
        f"{base_k}",
    ]
    branch_variants = [branch, branch_k]
    patterns: list[re.Pattern] = []
    sep = r"(?:の|ー|-)"
    for pre in prefixes:
        for b in base_variants:
            for br in branch_variants:
                pat = rf"^{pre}第?{b}条{sep}{br}$"
                patterns.append(re.compile(pat))
    return patterns


def build_branch_patterns_any(base: str) -> list[re.Pattern]:
    """Regex patterns for any branch number of given base (fullmatch)."""
    try:
        base_k = int_to_kanji(int(base))
    except Exception:
        base_k = base
    patterns: list[re.Pattern] = []
    sep = r"(?:の|ー|-)"
    branch_part = r"(\d+|[一二三四五六七八九十百千〇零]+)"
    for b in (base, base_k):
        pat = rf"^(?:法|令)?第?{b}条{sep}{branch_part}$"
        patterns.append(re.compile(pat))
    return patterns


def build_branch_search_patterns_any(base: str) -> list[re.Pattern]:
    """Regex patterns (search) for any branch number of given base (non-anchored)."""
    try:
        base_k = int_to_kanji(int(base))
    except Exception:
        base_k = base
    patterns: list[re.Pattern] = []
    sep = r"(?:の|ー|-)"
    branch_part = r"(\d+|[一二三四五六七八九十百千〇零]+)"
    for b in (base, base_k):
        pat = rf"(?:法|令)?第?{b}条{sep}{branch_part}"
        patterns.append(re.compile(pat))
    return patterns


def build_query_profile(query: str) -> dict:
    raw = query
    norm = normalize_separators(normalize_num(query))
    law_hint = ("法" in raw) or ("建築基準法" in raw)
    order_hint = ("令" in raw) or ("施行令" in raw)

    article_intent = ("条" in raw) or ("第" in raw) or bool(re.search(r"\d+条", norm))

    base = branch = None
    branch_any = False
    number_bases: list[str] = []
    m_branch = re.search(r"第?(\d+)条(?:の|ー|-)(\d+)$", norm)
    if m_branch:
        base, branch = m_branch.group(1), m_branch.group(2)
    else:
        m_branch_any = re.search(r"第?(\d+)条(?:の|ー|-)$", norm)
        if m_branch_any:
            base, branch_any = m_branch_any.group(1), True
        else:
            m_base = re.search(r"第?(\d+)条", norm)
            if m_base:
                base = m_base.group(1)
    if base:
        number_bases.append(base)
    elif not article_intent:
        number_bases.extend(extract_query_numbers(query))
    if not article_intent and number_bases:
        article_intent = True
    if base is None and number_bases:
        base = number_bases[0]

    title_terms = set()
    text_terms = set()
    text_patterns: list[re.Pattern] = []
    highlight_terms = set()

    def add_term_sets(terms: set[str]):
        title_terms.update(terms)
        text_terms.update(terms)
        highlight_terms.update(terms)

    prefixes = ["", "法", "令"]
    seps = ["の", "ー", "-"]

    def base_variants(b: str):
        try:
            b_kan = int_to_kanji(int(b))
        except Exception:
            b_kan = b
        return [b, b_kan]

    def branch_variants(br: str):
        try:
            br_kan = int_to_kanji(int(br))
        except Exception:
            br_kan = br
        return [br, br_kan]

    if article_intent and base:
        bvars = base_variants(base)
        if branch:
            brvars = branch_variants(branch)
            terms = set()
            for p in prefixes:
                for b in bvars:
                    for br in brvars:
                        for s in seps:
                            terms.add(f"{p}第{b}条{s}{br}")
            add_term_sets(terms)
            text_terms = terms.copy()
        elif branch_any:
            # number hits will rely on regex (branch required); terms used for highlight and text search
            terms = set()
            for p in prefixes:
                for b in bvars:
                    for s in seps:
                        terms.add(f"{p}第{b}条{s}")
            highlight_terms.update(terms)
            # text search uses regex requiring branch
            for b in bvars:
                text_patterns.append(
                    re.compile(rf"(?:法|令)?第?{b}条(?:の|ー|-)(\d+|[一二三四五六七八九十百千〇零]+)")
                )
        else:
            terms = set()
            for p in prefixes:
                for b in bvars:
                    terms.add(f"{p}第{b}条")
            add_term_sets(terms)
    else:
        nums = number_bases or extract_query_numbers(query)
        if nums:
            for num in nums:
                bvars = base_variants(num)
                bare_terms = set()
                for b in bvars:
                    bare_terms.add(b)
                    bare_terms.add(f"第{b}条")
                    bare_terms.add(f"法第{b}条")
                    bare_terms.add(f"令第{b}条")
                add_term_sets(bare_terms)
        # include raw query as text term for loose match
        text_terms.add(raw)
        highlight_terms.update(text_terms)

    return {
        "raw": raw,
        "norm": norm,
        "law_hint": law_hint,
        "order_hint": order_hint,
        "article_intent": article_intent,
        "base": base,
        "branch": branch,
        "branch_any": branch_any,
        "number_bases": number_bases,
        "title_terms_raw": title_terms,
        "title_terms_norm": {normalize_separators(normalize_num(t)) for t in title_terms},
        "text_terms_raw": text_terms,
        "text_terms_norm": {normalize_separators(normalize_num(t)) for t in text_terms},
        "text_patterns": text_patterns,
        "highlight_terms": highlight_terms,
    }


def build_formal_patterns(base: str, branch: str | None):
    """Return (title_patterns, text_patterns) for formal article matching."""
    try:
        base_k = int_to_kanji(int(base))
    except Exception:
        base_k = base
    branch_k = None
    if branch is not None:
        try:
            branch_k = int_to_kanji(int(branch))
        except Exception:
            branch_k = branch

    prefixes = ["", "法", "令"]
    title_patterns = []
    text_patterns = []

    def add_patterns(b, br):
        if br is None:
            title_patterns.append(re.compile(rf"^(?:法|令)?第?{b}条$"))
            text_patterns.append(re.compile(rf"(?:法|令)?第?{b}条(?![の0-9一二三四五六七八九十百千])"))
        else:
            title_patterns.append(re.compile(rf"^(?:法|令)?第?{b}条(?:の|ー|-){br}$"))
            text_patterns.append(
                re.compile(rf"(?:法|令)?第?{b}条(?:の|ー|-){br}(?![0-9一二三四五六七八九十百千])")
            )

    add_patterns(base, branch)
    add_patterns(base_k, branch_k)

    return title_patterns, text_patterns


def matches_branch_patterns(text: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


def build_article_context_map(root: ET.Element):
    """
    MainProvision 内の Article ごとに章タイトル・節タイトルをマッピングする。
    節がない場合 section_title は None。
    """
    context = {}
    main_provision = root.find(".//{*}MainProvision")
    if main_provision is None:
        return context

    for chapter in main_provision.findall("./{*}Chapter"):
        chapter_title = chapter.findtext("./{*}ChapterTitle") or None

        for section in chapter.findall("./{*}Section"):
            section_title = section.findtext("./{*}SectionTitle") or None
            for art in section.findall("./{*}Article"):
                context[art] = {
                    "chapter_title": chapter_title,
                    "section_title": section_title or None,
                }

        for art in chapter.findall("./{*}Article"):
            context.setdefault(
                art, {"chapter_title": chapter_title, "section_title": None}
            )

    return context


def get_article_base_number(title: str) -> str | None:
    """ArticleTitle から条の基番号（数字）を抽出する。"""
    t_norm = normalize_num(title)
    m = re.search(r"第(\d+)条", t_norm)
    if m:
        return m.group(1)
    return None


def search_articles_simple(root: ET.Element, profile: dict):
    """単純化した検索ロジックで条番号一致／本文中一致を返す。"""
    results_number = []
    results_text = []
    context_map = build_article_context_map(root)

    title_terms_raw = profile["title_terms_raw"]
    title_terms_norm = profile["title_terms_norm"]
    text_terms_raw = profile["text_terms_raw"]
    text_terms_norm = profile["text_terms_norm"]
    text_patterns = profile["text_patterns"]

    base = profile["base"]
    branch = profile["branch"]
    branch_any = profile["branch_any"]
    article_intent = profile["article_intent"]
    number_bases = profile.get("number_bases", [])

    branch_any_anchored = build_branch_patterns_any(base) if branch_any and base else []
    branch_any_search = build_branch_search_patterns_any(base) if branch_any and base else []
    branch_exact_patterns = build_branch_patterns(base, branch) if (branch and base) else []

    base_patterns_anchored = []
    if article_intent or number_bases:
        bases = [base] if base else number_bases
        for b_base in bases:
            try:
                b_kan = int_to_kanji(int(b_base))
            except Exception:
                b_kan = b_base
            branch_part = r"(?:(?:の|ー|-)(?:\d+|[一二三四五六七八九十百千〇零]+))?"
            for b in (b_base, b_kan):
                base_patterns_anchored.append(re.compile(rf"^(?:法|令)?第?{b}条{branch_part}$"))

    def build_entry(art):
        title = art.findtext(".//{*}ArticleTitle") or ""
        caption = art.findtext(".//{*}ArticleCaption") or ""
        struct = extract_structure(art)
        full_plain = render_article_plain(title, struct)
        body_lines = full_plain.splitlines()
        body_plain = "\n".join(body_lines[1:]) if len(body_lines) > 1 else ""
        ctx = context_map.get(art, {})
        return {
            "title": title,
            "caption": caption,
            "structure": struct,
            "full_text": full_plain,
            "body_text": body_plain,
            "chapter_title": ctx.get("chapter_title"),
            "section_title": ctx.get("section_title"),
        }

    for art in root.findall(".//{*}MainProvision//{*}Article"):
        entry = build_entry(art)
        title_raw = entry["title"]
        title_norm = normalize_separators(normalize_num(title_raw))
        body_source = entry.get("body_text") or ""
        body_raw = clean_text_display(entry["caption"] + body_source)
        body_norm = normalize_separators(normalize_num(body_raw))

        # 条番号一致
        title_match = False
        if branch and branch_exact_patterns:
            title_match = any(p.fullmatch(title_raw) or p.fullmatch(title_norm) for p in branch_exact_patterns)
        elif branch_any and branch_any_anchored:
            title_match = any(p.fullmatch(title_raw) or p.fullmatch(title_norm) for p in branch_any_anchored)
        elif (article_intent or number_bases) and base_patterns_anchored:
            title_match = any(p.fullmatch(title_raw) or p.fullmatch(title_norm) for p in base_patterns_anchored)
            if not title_match and base:
                try:
                    base_kan = int_to_kanji(int(base))
                except Exception:
                    base_kan = base
                fallback_pat = re.compile(rf"^(?:法|令)?第?(?:{base}|{base_kan})条(?:の|ー|-)?\d*$")
                if fallback_pat.match(title_norm):
                    title_match = True
        else:
            if title_raw in title_terms_raw or title_norm in title_terms_norm:
                title_match = True

        if title_match:
            results_number.append(entry)

        # 本文中一致（常に実行）
        text_hit = False
        if branch:
            for term in text_terms_raw:
                if term and (term in body_raw or term in body_norm):
                    text_hit = True
                    break
            if not text_hit:
                for term in text_terms_norm:
                    if term and (term in body_norm or term in body_raw):
                        text_hit = True
                        break
            if not text_hit and text_patterns:
                text_hit = any(p.search(body_raw) or p.search(body_norm) for p in text_patterns)
        elif branch_any and branch_any_search:
            text_hit = any(p.search(body_raw) or p.search(body_norm) for p in branch_any_search)
        else:
            if any(term and (term in body_raw or term in body_norm) for term in text_terms_raw):
                text_hit = True
            elif any(term and (term in body_raw or term in body_norm) for term in text_terms_norm):
                text_hit = True
            elif text_patterns and any(p.search(body_raw) or p.search(body_norm) for p in text_patterns):
                text_hit = True

        if text_hit:
            results_text.append(entry)

    return {"number_hits": results_number, "text_hits": results_text}


def search_both_laws(root_main, root_order, query: str):
    profile = build_query_profile(query)

    results = {
        "法": search_articles_simple(root_main, profile),
        "令": search_articles_simple(root_order, profile),
    }

    if profile["law_hint"] and not profile["order_hint"]:
        results["令"]["number_hits"] = []
    elif profile["order_hint"] and not profile["law_hint"]:
        results["法"]["number_hits"] = []

    return results
