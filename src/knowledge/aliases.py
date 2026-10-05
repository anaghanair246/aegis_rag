"""Identifier normalisation + alias resolution policy.

POLICY (non-obvious decisions, justified):
 * Aliases are merged ONLY on explicit evidence (register 'Known Aliases', or a sentence that says two terms
   are the same thing). Never by string similarity: PS-04, PS-04A and PS-40 are one edit apart and are three
   different components (register rows + ECN-1042 'not form-fit-function' + register note on PS-40).
 * Normalisation (case, hyphen, space, underscore) only removes *formatting* variance: 'PS04A' == 'PS-04A'.
 * PS-04 -> PS-04A is represented as a 'supersedes' edge with a software-revision scope, not as identity.
"""
import re

_SEP = re.compile(r"[\s_\-./]+")


def norm(s: str) -> str:
    return _SEP.sub("", (s or "")).upper()


def tokens_in_text(text: str):
    """Candidate identifier tokens in free text (PS-04A, PS04A, IV-21, A17, TB-7, PLC-03, J-14 ...)."""
    pat = r"\b(?:PS|IV|TB|PLC|J|P|KA|Q|T)[-\s]?\d{1,3}[A-Z]?\b|\bA\d{2}\b|\bHPU\b"
    return [m.group(0) for m in re.finditer(pat, text)]


def sw_tuple(v):
    if v is None:
        return None
    return tuple(int(x) for x in re.findall(r"\d+", str(v)))


def sw_in_scope(sw, sw_from, sw_before) -> bool:
    """True if software revision `sw` falls within [sw_from, sw_before). None bounds are open."""
    s = sw_tuple(sw)
    if s is None:
        return True
    f, b = sw_tuple(sw_from), sw_tuple(sw_before)
    return (f is None or s >= f) and (b is None or s < b)
