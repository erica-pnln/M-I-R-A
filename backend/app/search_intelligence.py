import re
from datetime import date, timedelta


_PREFIX = re.compile(
    r"^\s*(?:(?:please\s+)?(?:show|find|search for|look up)\s+)?"
    r"(?:(?:me|us)\s+)?(?:(?:the\s+)?(?:news|reports|articles|stories)\s+)?"
    r"(?:about|on|regarding|for)\s+",
    re.IGNORECASE,
)
_YEAR_RANGE = re.compile(r"\b(?:from\s+)?(19\d{2}|20\d{2})\s+(?:to|through|until|-)\s+(19\d{2}|20\d{2})\b", re.I)
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
_DATE_RANGE = re.compile(
    r"\b(?:from\s+)?(\d{4}-\d{2}-\d{2})\s+(?:to|through|until|-)\s+(\d{4}-\d{2}-\d{2})\b",
    re.I,
)
_FILLER = re.compile(
    r"\b(?:during|in|between|from|to|through|until|the|please|show|me|news|reports|"
    r"articles|stories|about|for|on|what|were|was|are|is|happened|with|related|"
    r"regarding|find|search|look|up|his|her|their)\b",
    re.I,
)


def understand_query(
    query: str,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict:
    """Normalize a natural-language news query and extract explicit date bounds."""
    text = " ".join(query.split())
    start = from_date
    end = to_date
    has_explicit_year = False

    date_range = _DATE_RANGE.search(text)
    year_range = _YEAR_RANGE.search(text)
    if date_range:
        start = start or date.fromisoformat(date_range.group(1))
        end = end or date.fromisoformat(date_range.group(2))
        has_explicit_year = True
        text = text[:date_range.start()] + " " + text[date_range.end():]
    elif year_range:
        first_year, last_year = map(int, year_range.groups())
        start = start or date(first_year, 1, 1)
        end = end or date(last_year, 12, 31)
        has_explicit_year = True
        text = text[:year_range.start()] + " " + text[year_range.end():]
    else:
        year = _YEAR.search(text)
        if year:
            year_value = int(year.group(1))
            start = start or date(year_value, 1, 1)
            end = end or date(year_value, 12, 31)
            has_explicit_year = True
            text = text[:year.start()] + " " + text[year.end():]

    text = _PREFIX.sub("", text)
    if has_explicit_year:
        text = re.sub(r"\byear\b", " ", text, flags=re.IGNORECASE)
    text = _FILLER.sub(" ", text)
    normalized = re.sub(r"\s+", " ", text).strip(" ,?.")
    return {
        "query": normalized,
        "from_date": start,
        "to_date": end,
    }


def query_with_dates(
    query: str,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    period: str = "all",
    today: date | None = None,
) -> tuple[str, date | None, date | None]:
    """Add Google News RSS date operators and return the effective date range."""
    current = today or date.today()
    start, end = from_date, to_date
    if period == "latest":
        start = max(start, current - timedelta(days=30)) if start else current - timedelta(days=30)
    elif period == "historical":
        cutoff = current - timedelta(days=30)
        end = min(end, cutoff) if end else cutoff

    operators = []
    if start:
        operators.append(f"after:{start.isoformat()}")
    if end:
        operators.append(f"before:{(end + timedelta(days=1)).isoformat()}")
    search_query = " ".join(part for part in (query, *operators) if part)
    return search_query, start, end
