"""Read-only movie folder and filename checks against Jellyfin metadata.

The report operates on the existing Jellyfin snapshot without accessing or
modifying media files.
"""
import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Tuple


VERSION_TAG_RE = re.compile(r"\s+-\s+\[[^\]]+\]$")


YEAR_AT_END_RE = re.compile(r"^(?P<title>.*?)(?:\s*\((?P<year>\d{4})\))?$")


INCORRECT_VERSION_TAG_PART = r"""
(?:
    director(?:'|’)?s[\s._-]*cut
  | directors[\s._-]*cut
  | unrated
  | extended(?:[\s._-]*cut)?
  | remastered
  | alternate(?:[\s._-]*ending)?
)
"""


INCORRECT_VERSION_SUFFIX_RE = re.compile(
    rf"""
    (?:[\s._-]*(?:and|&)[\s._-]*|[\s._-]+)?
    (?P<tag>{INCORRECT_VERSION_TAG_PART})
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


TRAILING_JOINER_RE = re.compile(
    r"(?:[\s._-]*(?:and|&)[\s._-]*|[\s._-]+)$",
    re.IGNORECASE,
)


CATEGORY_ORDER = [
    "everything matches exactly",
    "ignoring case, everything matches exactly",
    "ignoring symbols and case, everything matches exactly",
    "ignoring symbols and case, year is the only thing wrong (off by 1)",
    "ignoring symbols and case, year is the only thing wrong (off by more than 1)",
    "some issue like spelling",
    "possible misidentified",
]


CATEGORY_RANK = {category: i for i, category in enumerate(CATEGORY_ORDER)}


ROMAN_NUMERAL_MAP = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
    "xi": "11",
    "xii": "12",
    "xiii": "13",
    "xiv": "14",
    "xv": "15",
    "xvi": "16",
    "xvii": "17",
    "xviii": "18",
    "xix": "19",
    "xx": "20",
}


ARABIC_TO_ROMAN_MAP = {v: k for k, v in ROMAN_NUMERAL_MAP.items()}


ROMAN_TOKEN_RE = re.compile(
    r"\b(" + "|".join(sorted(ROMAN_NUMERAL_MAP.keys(), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


ARABIC_TOKEN_RE = re.compile(
    r"\b(" + "|".join(sorted(ARABIC_TO_ROMAN_MAP.keys(), key=lambda x: (len(x), x), reverse=True)) + r")\b"
)


def ascii_fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def normalize_case_only(text: str) -> str:
    return ascii_fold(text).casefold()


def normalize_alnum_only(text: str) -> str:
    text = ascii_fold(text).casefold()
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def similarity(a: str, b: str) -> float:
    return round(100.0 * SequenceMatcher(None, a, b).ratio(), 2)


def strip_version_tag(file_stem: str) -> str:
    return VERSION_TAG_RE.sub("", file_stem).strip()


def parse_title_year(component: str) -> Tuple[str, str]:
    component = component.strip()
    m = YEAR_AT_END_RE.match(component)
    if not m:
        return component, ""
    return (m.group("title") or "").strip(), (m.group("year") or "").strip()


def build_expected_component(title: str, year: str) -> str:
    title = (title or "").strip()
    year = (year or "").strip()
    return f"{title} ({year})" if year else title


def extract_path_parts(path: str) -> Dict[str, str]:
    norm = os.path.normpath(path)
    folder_component = os.path.basename(os.path.dirname(norm))
    filename = os.path.basename(norm)
    file_stem, file_ext = os.path.splitext(filename)
    file_component = strip_version_tag(file_stem)

    return {
        "folder_component": folder_component,
        "file_component": file_component,
        "file_ext": file_ext,
    }


def strip_incorrect_version_tags(title: str) -> Tuple[str, bool, List[str]]:
    working = title.rstrip()
    removed: List[str] = []

    while True:
        m = INCORRECT_VERSION_SUFFIX_RE.search(working)
        if not m:
            break

        removed.insert(0, m.group("tag").strip())
        working = working[: m.start()].rstrip(" ._-")
        working = TRAILING_JOINER_RE.sub("", working).rstrip(" ._-")

    return working.strip(), bool(removed), removed


def replace_ampersand_with_and(text: str) -> str:
    return text.replace("&", " and ")


def replace_and_with_ampersand(text: str) -> str:
    return re.sub(r"\band\b", "&", text, flags=re.IGNORECASE)


def roman_to_arabic(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0).casefold()
        return ROMAN_NUMERAL_MAP.get(token, token)
    return ROMAN_TOKEN_RE.sub(repl, text)


def arabic_to_roman(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        roman = ARABIC_TO_ROMAN_MAP.get(token)
        return roman if roman is not None else token
    return ARABIC_TOKEN_RE.sub(repl, text)


def remove_after_colon(text: str) -> str:
    if ":" not in text:
        return text
    return text.split(":", 1)[0].rstrip()


def title_variants(text: str) -> Dict[str, str]:
    variants: Dict[str, str] = {}

    def add(label: str, value: str) -> None:
        value = re.sub(r"\s+", " ", value).strip()
        if value and value not in variants.values():
            variants[label] = value

    base = text.strip()
    add("raw", base)

    add("amp_to_and", replace_ampersand_with_and(base))
    add("and_to_amp", replace_and_with_ampersand(base))

    add("roman_to_arabic", roman_to_arabic(base))
    add("arabic_to_roman", arabic_to_roman(base))

    a1 = replace_ampersand_with_and(base)
    add("amp_to_and__roman_to_arabic", roman_to_arabic(a1))
    add("amp_to_and__arabic_to_roman", arabic_to_roman(a1))

    a2 = replace_and_with_ampersand(base)
    add("and_to_amp__roman_to_arabic", roman_to_arabic(a2))
    add("and_to_amp__arabic_to_roman", arabic_to_roman(a2))

    colon_trimmed = remove_after_colon(base)
    if colon_trimmed != base:
        add("colon_trimmed", colon_trimmed)
        add("colon_trimmed__amp_to_and", replace_ampersand_with_and(colon_trimmed))
        add("colon_trimmed__and_to_amp", replace_and_with_ampersand(colon_trimmed))
        add("colon_trimmed__roman_to_arabic", roman_to_arabic(colon_trimmed))
        add("colon_trimmed__arabic_to_roman", arabic_to_roman(colon_trimmed))

        c1 = replace_ampersand_with_and(colon_trimmed)
        add("colon_trimmed__amp_to_and__roman_to_arabic", roman_to_arabic(c1))
        add("colon_trimmed__amp_to_and__arabic_to_roman", arabic_to_roman(c1))

        c2 = replace_and_with_ampersand(colon_trimmed)
        add("colon_trimmed__and_to_amp__roman_to_arabic", roman_to_arabic(c2))
        add("colon_trimmed__and_to_amp__arabic_to_roman", arabic_to_roman(c2))

    return variants


def compare_titles_best(expected_title: str, actual_title: str) -> Dict[str, object]:
    exp_variants = title_variants(expected_title)
    act_variants = title_variants(actual_title)

    exact = False
    case = False
    symbol = False

    best_similarity = 0.0
    best_pair = ("raw", "raw")
    best_values = (expected_title, actual_title)

    strong_colon_candidate = False
    strong_colon_pair = None

    for exp_label, exp_value in exp_variants.items():
        for act_label, act_value in act_variants.items():
            exp_case = normalize_case_only(exp_value)
            act_case = normalize_case_only(act_value)
            exp_alnum = normalize_alnum_only(exp_value)
            act_alnum = normalize_alnum_only(act_value)

            is_exact = exp_value == act_value
            is_case = exp_case == act_case
            is_symbol = exp_alnum == act_alnum

            score = similarity(exp_alnum, act_alnum)

            if score > best_similarity:
                best_similarity = score
                best_pair = (exp_label, act_label)
                best_values = (exp_value, act_value)

            pair_uses_colon = ("colon_trimmed" in exp_label) or ("colon_trimmed" in act_label)
            strong_match = is_exact or is_case or is_symbol

            if pair_uses_colon and strong_match:
                strong_colon_candidate = True
                if strong_colon_pair is None:
                    strong_colon_pair = {
                        "exact": is_exact,
                        "case": is_case,
                        "symbol": is_symbol,
                        "pair": (exp_label, act_label),
                        "values": (exp_value, act_value),
                        "score": score,
                    }
                else:
                    current_rank = 0 if strong_colon_pair["exact"] else 1 if strong_colon_pair["case"] else 2
                    new_rank = 0 if is_exact else 1 if is_case else 2
                    if new_rank < current_rank or (new_rank == current_rank and score > strong_colon_pair["score"]):
                        strong_colon_pair = {
                            "exact": is_exact,
                            "case": is_case,
                            "symbol": is_symbol,
                            "pair": (exp_label, act_label),
                            "values": (exp_value, act_value),
                            "score": score,
                        }

            exact = exact or is_exact
            case = case or is_case
            symbol = symbol or is_symbol

    if strong_colon_candidate and strong_colon_pair is not None:
        return {
            "exact_match": strong_colon_pair["exact"],
            "case_match": strong_colon_pair["case"],
            "symbol_case_match": strong_colon_pair["symbol"],
            "best_similarity": round(max(best_similarity, strong_colon_pair["score"]), 2),
            "best_variant_pair": strong_colon_pair["pair"],
            "best_variant_values": strong_colon_pair["values"],
            "used_colon_trimmed_variant": True,
        }

    return {
        "exact_match": exact,
        "case_match": case,
        "symbol_case_match": symbol,
        "best_similarity": round(best_similarity, 2),
        "best_variant_pair": best_pair,
        "best_variant_values": best_values,
        "used_colon_trimmed_variant": False,
    }


def compute_year_delta(actual_year: str, expected_year: str) -> int | None:
    if not actual_year or not expected_year:
        return None
    if not actual_year.isdigit() or not expected_year.isdigit():
        return None
    return abs(int(actual_year) - int(expected_year))


def evaluate_component(
    raw_component: str,
    expected_title: str,
    expected_year: str,
    expected_component: str,
    spelling_threshold: float,
) -> Dict[str, object]:
    raw_title, raw_year = parse_title_year(raw_component)

    cleaned_title, has_bad_version_tag, removed_tags = strip_incorrect_version_tags(raw_title)
    cleaned_component = build_expected_component(cleaned_title, raw_year)

    year_matches = raw_year == expected_year
    year_delta = compute_year_delta(raw_year, expected_year)

    component_compare = compare_titles_best(expected_component, cleaned_component)
    title_compare = compare_titles_best(expected_title, cleaned_title)

    exact_match = bool(component_compare["exact_match"])
    case_match = bool(component_compare["case_match"])
    symbol_case_match = bool(component_compare["symbol_case_match"])

    title_symbol_case_match = bool(title_compare["symbol_case_match"])
    title_similarity = float(title_compare["best_similarity"])

    if exact_match:
        category = "everything matches exactly"
    elif case_match:
        category = "ignoring case, everything matches exactly"
    elif symbol_case_match:
        category = "ignoring symbols and case, everything matches exactly"
    elif title_symbol_case_match and not year_matches:
        if year_delta is not None and year_delta <= 1:
            category = "ignoring symbols and case, year is the only thing wrong (off by 1)"
        else:
            category = "ignoring symbols and case, year is the only thing wrong (off by more than 1)"
    elif title_similarity >= spelling_threshold:
        category = "some issue like spelling"
    else:
        category = "possible misidentified"

    return {
        "raw_component": raw_component,
        "raw_title": raw_title,
        "raw_year": raw_year,
        "cleaned_title": cleaned_title,
        "cleaned_component": cleaned_component,
        "year_matches": year_matches,
        "year_delta": year_delta,
        "exact_match": exact_match,
        "case_match": case_match,
        "symbol_case_match": symbol_case_match,
        "title_symbol_case_match": title_symbol_case_match,
        "title_similarity": title_similarity,
        "incorrect_version_tag": has_bad_version_tag,
        "removed_version_tags": removed_tags,
        "category": category,
        "rank": CATEGORY_RANK[category],
        "component_best_variant_pair": component_compare["best_variant_pair"],
        "component_best_variant_values": component_compare["best_variant_values"],
        "title_best_variant_pair": title_compare["best_variant_pair"],
        "title_best_variant_values": title_compare["best_variant_values"],
        "used_colon_trimmed_variant": bool(component_compare["used_colon_trimmed_variant"]) or bool(
            title_compare["used_colon_trimmed_variant"]
        ),
    }


def choose_overall_bucket(folder_eval: Dict[str, object], file_eval: Dict[str, object]) -> Tuple[str, str]:
    folder_rank = int(folder_eval["rank"])
    file_rank = int(file_eval["rank"])

    if folder_rank < file_rank:
        return str(folder_eval["category"]), "folder"
    if file_rank < folder_rank:
        return str(file_eval["category"]), "file"

    folder_similarity = float(folder_eval["title_similarity"])
    file_similarity = float(file_eval["title_similarity"])

    if folder_similarity > file_similarity:
        return str(folder_eval["category"]), "folder"
    if file_similarity > folder_similarity:
        return str(file_eval["category"]), "file"

    return str(folder_eval["category"]), "both"


def classify_row(row: Dict[str, str], spelling_threshold: float) -> Dict[str, object]:
    title = (row.get("title") or "").strip()
    year = (row.get("year") or "").strip()
    path = (row.get("path") or "").strip()

    expected_component = build_expected_component(title, year)
    path_parts = extract_path_parts(path)

    folder_component = path_parts["folder_component"]
    file_component = path_parts["file_component"]

    folder_file_exact_match = folder_component == file_component

    folder_eval = evaluate_component(
        raw_component=folder_component,
        expected_title=title,
        expected_year=year,
        expected_component=expected_component,
        spelling_threshold=spelling_threshold,
    )

    file_eval = evaluate_component(
        raw_component=file_component,
        expected_title=title,
        expected_year=year,
        expected_component=expected_component,
        spelling_threshold=spelling_threshold,
    )

    overall_category, bucket_source = choose_overall_bucket(folder_eval, file_eval)

    incorrectly_formatted_version_tag = bool(folder_eval["incorrect_version_tag"]) or bool(
        file_eval["incorrect_version_tag"]
    )

    best_title_similarity = max(
        float(folder_eval["title_similarity"]),
        float(file_eval["title_similarity"]),
    )

    notes: List[str] = []

    if not folder_file_exact_match:
        notes.append("folder/file differ exactly")

    if incorrectly_formatted_version_tag:
        bad_sides = []
        if bool(folder_eval["incorrect_version_tag"]):
            bad_sides.append("folder")
        if bool(file_eval["incorrect_version_tag"]):
            bad_sides.append("file")
        notes.append(f"incorrect version tag in {'/'.join(bad_sides)}")

    if bool(folder_eval["used_colon_trimmed_variant"]) or bool(file_eval["used_colon_trimmed_variant"]):
        notes.append("colon-trimmed variant improved matching")

    if overall_category.startswith("ignoring symbols and case, year is the only thing wrong"):
        deltas = [d for d in [folder_eval["year_delta"], file_eval["year_delta"]] if d is not None]
        if deltas:
            notes.append(f"best year delta {min(deltas)}")

    if overall_category == "some issue like spelling":
        notes.append(f"best title similarity {best_title_similarity:.2f}%")
    elif overall_category == "possible misidentified":
        notes.append(f"best title similarity only {best_title_similarity:.2f}%")

    return {
        "title": title,
        "year": year,
        "path": path,
        "expected_component": expected_component,
        "category": overall_category,
        "bucket_source": bucket_source,
        "best_title_similarity": best_title_similarity,
        "folder_file_exact_match": folder_file_exact_match,
        "incorrectly_formatted_version_tag": incorrectly_formatted_version_tag,
        "folder_component": folder_component,
        "file_component": file_component,
        "folder_cleaned_component": str(folder_eval["cleaned_component"]),
        "file_cleaned_component": str(file_eval["cleaned_component"]),
        "folder_category": str(folder_eval["category"]),
        "file_category": str(file_eval["category"]),
        "folder_year_matches_metadata": bool(folder_eval["year_matches"]),
        "file_year_matches_metadata": bool(file_eval["year_matches"]),
        "folder_year_delta": folder_eval["year_delta"],
        "file_year_delta": file_eval["year_delta"],
        "folder_title_similarity": float(folder_eval["title_similarity"]),
        "file_title_similarity": float(file_eval["title_similarity"]),
        "folder_incorrectly_formatted_version_tag": bool(folder_eval["incorrect_version_tag"]),
        "file_incorrectly_formatted_version_tag": bool(file_eval["incorrect_version_tag"]),
        "folder_removed_version_tags": list(folder_eval["removed_version_tags"]),
        "file_removed_version_tags": list(file_eval["removed_version_tags"]),
        "folder_best_variant_pair": folder_eval["title_best_variant_pair"],
        "file_best_variant_pair": file_eval["title_best_variant_pair"],
        "notes": "; ".join(notes),
    }


def row_needs_stdout(row: Dict[str, object]) -> bool:
    return not (
        row["category"] == "everything matches exactly"
        and bool(row["folder_file_exact_match"])
        and not bool(row["incorrectly_formatted_version_tag"])
    )


DEFAULT_SPELLING_THRESHOLD = 92.0


def analyze_movies(media_rows, spelling_threshold=DEFAULT_SPELLING_THRESHOLD):
    """Return one report row per movie version without accessing media files."""
    rows = []
    counts = {category: 0 for category in CATEGORY_ORDER}
    summary = {
        'total_movies': 0, 'checked': 0, 'needs_review': 0, 'uncheckable': 0,
        'folder_file_mismatches': 0, 'bad_version_tags': 0,
    }
    for media in media_rows:
        if media.get('type') != 'Movie':
            continue
        summary['total_movies'] += 1
        title = (media.get('metadata_title') or '').strip()
        year = media.get('production_year')
        path = media.get('path')
        missing = []
        if not title:
            missing.append('Jellyfin title')
        if year is None:
            missing.append('Jellyfin production year')
        if not path or not os.path.isabs(path):
            missing.append('absolute media path')
        common = {
            'id': media['id'], 'version_name': media.get('version_name', ''),
            'title': title or media.get('name', 'Unknown'), 'year': str(year) if year is not None else '',
            'path': path, 'uncheckable_reason': '',
        }
        if missing:
            rows.append({**common, 'status': 'uncheckable', 'needs_review': True,
                         'uncheckable_reason': 'Missing ' + ', '.join(missing) + '.'})
            summary['uncheckable'] += 1
            continue
        result = classify_row({'title': title, 'year': str(year), 'path': path}, spelling_threshold)
        needs_review = row_needs_stdout(result)
        rows.append({**result, **common, 'status': 'checked', 'needs_review': needs_review})
        counts[result['category']] += 1
        summary['checked'] += 1
        summary['needs_review'] += int(needs_review)
        summary['folder_file_mismatches'] += int(not result['folder_file_exact_match'])
        summary['bad_version_tags'] += int(result['incorrectly_formatted_version_tag'])
    summary['categories'] = [{'category': category, 'count': count} for category, count in counts.items()]
    rows.sort(key=lambda row: (
        CATEGORY_RANK.get(row.get('category'), len(CATEGORY_ORDER)),
        -row.get('best_title_similarity', 0), row['title'].casefold(), (row['path'] or '').casefold(),
    ))
    return {'spelling_threshold': spelling_threshold, 'summary': summary, 'rows': rows}
