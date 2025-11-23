# -*- coding: utf-8 -*-
try:
    # Package (python -m src.app)
    from .laws_api import BASE_URL, LAW_MAIN_ID, LAW_ORDER_ID, fetch_law_xml, safe_fetch
    from .number_text_utils import (
        DASH_TRANSLATE,
        KANJI_DIGITS,
        KANJI_DIGITS_REV,
        KANJI_SEQ_RE,
        KANJI_UNITS,
        _kanji_seq_to_int,
        int_to_kanji,
        normalize_num,
        normalize_separators,
    )
    from .search_logic import (
        build_article_context_map,
        build_branch_patterns,
        build_branch_patterns_any,
        build_branch_search_patterns_any,
        build_formal_patterns,
        build_query_profile,
        build_term_groups,
        extract_query_numbers,
        generate_number_terms,
        get_article_base_number,
        is_branch_mode,
        matches_branch_patterns,
        matches_group,
        parse_number_token,
        search_articles_simple,
        search_both_laws,
    )
    from .structure_extract import (
        _extract_items,
        _extract_sentences,
        extract_structure,
        prune_empty,
        render_article_plain,
        render_structure,
    )
    from .text_utils import clean_text_display, get_text
    from .ui_app import Building_Code_Search, highlight_text, make_safe_id
except ImportError:
    # Script direct (python src/app.py)
    from laws_api import BASE_URL, LAW_MAIN_ID, LAW_ORDER_ID, fetch_law_xml, safe_fetch
    from number_text_utils import (
        DASH_TRANSLATE,
        KANJI_DIGITS,
        KANJI_DIGITS_REV,
        KANJI_SEQ_RE,
        KANJI_UNITS,
        _kanji_seq_to_int,
        int_to_kanji,
        normalize_num,
        normalize_separators,
    )
    from search_logic import (
        build_article_context_map,
        build_branch_patterns,
        build_branch_patterns_any,
        build_branch_search_patterns_any,
        build_formal_patterns,
        build_query_profile,
        build_term_groups,
        extract_query_numbers,
        generate_number_terms,
        get_article_base_number,
        is_branch_mode,
        matches_branch_patterns,
        matches_group,
        parse_number_token,
        search_articles_simple,
        search_both_laws,
    )
    from structure_extract import (
        _extract_items,
        _extract_sentences,
        extract_structure,
        prune_empty,
        render_article_plain,
        render_structure,
    )
    from text_utils import clean_text_display, get_text
    from ui_app import Building_Code_Search, highlight_text, make_safe_id

__all__ = [
    "BASE_URL",
    "LAW_MAIN_ID",
    "LAW_ORDER_ID",
    "fetch_law_xml",
    "safe_fetch",
    "DASH_TRANSLATE",
    "KANJI_DIGITS",
    "KANJI_DIGITS_REV",
    "KANJI_SEQ_RE",
    "KANJI_UNITS",
    "_kanji_seq_to_int",
    "int_to_kanji",
    "normalize_num",
    "normalize_separators",
    "build_article_context_map",
    "build_branch_patterns",
    "build_branch_patterns_any",
    "build_branch_search_patterns_any",
    "build_formal_patterns",
    "build_query_profile",
    "build_term_groups",
    "extract_query_numbers",
    "generate_number_terms",
    "get_article_base_number",
    "is_branch_mode",
    "matches_branch_patterns",
    "matches_group",
    "parse_number_token",
    "search_articles_simple",
    "search_both_laws",
    "_extract_items",
    "_extract_sentences",
    "extract_structure",
    "prune_empty",
    "render_article_plain",
    "render_structure",
    "clean_text_display",
    "get_text",
    "Building_Code_Search",
    "highlight_text",
    "make_safe_id",
]


if __name__ == "__main__":
    Building_Code_Search().run()
