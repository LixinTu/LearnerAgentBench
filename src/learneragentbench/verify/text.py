"""Whether a text mentions a keyword. Plain substring matching judged real runs wrongly: "lab" fired on "available",
"late" on "calculate", "mom" on "moment", "on call" on "function call", "82" on "0.822", "november 1" on "November 14th".
A keyword is a whole word with its ordinary endings; a number stands alone."""
from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=4096)
def _pattern(keyword: str) -> re.Pattern[str]:
    kw = keyword.strip().lower()
    body = re.escape(kw)
    if not kw[0].isalnum() or not kw[-1].isalnum():
        return re.compile(body)  # "%" and "/100" sit right against the number before them
    if kw[-1].isdigit():
        # "82/100", "$82", "82%", "november 9th" and "82.0" count; "0.82", "182", "820", "19:82" and "2026-11-82" do not.
        return re.compile(rf"(?<![\w.:,])(?<!\d-){body}(?:st|nd|rd|th)?(?!\w)(?!\.\d*[1-9])")
    last = re.escape(kw[-1])
    return re.compile(rf"(?<!\w){body}(?:s|es|d|ed|ing|{last}es|{last}ed|{last}ing)?(?!\w)")


def mentions(keyword: object, text: str) -> bool:
    """Does ``text`` mention ``keyword``? Case-insensitive; "friday" finds "Fridays", "stop" finds "stopped"."""
    return bool(_pattern(str(keyword)).search(text.lower()))


def mentions_one_of(keywords: object, text: str) -> bool:
    """For a parameter that is one keyword or a list of alternatives."""
    return any(mentions(k, text) for k in (keywords if isinstance(keywords, list) else [keywords]))


def mentions_any(keywords: list[object], text: str) -> list[str]:
    """The keywords that ``text`` mentions."""
    return [str(k) for k in keywords if mentions(k, text)]
