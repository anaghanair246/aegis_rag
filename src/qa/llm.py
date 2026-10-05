"""Optional LLM answering path (used ONLY when no rule handler recognises the question and AEGIS_USE_LLM=1).
STATUS: UNVERIFIED against a live model in the build sandbox (no API key). Covered by mock-client tests only.

Safety design: the model sees only retrieved passages + the structured fact sheet for resolved entities and must
return JSON with passage-id citations. Output is REJECTED (-> abstention) if: JSON invalid, any cited passage id was
not in the retrieved set, any claim lacks a citation, or a number+unit in the answer is absent from the cited text."""
import json
import os
import re
from typing import List, Optional
from src import config
from src.qa.models import Answer, Claim, ANSWERED, CAVEATS, CONFLICT, INSUFFICIENT

SYSTEM = """You answer questions about the Aegis Series-7 Hydraulic Control System using ONLY the numbered passages given.
Rules: (1) Every claim must cite passage ids from the list. (2) Never use outside knowledge, never guess values or units.
(3) Facts are version-scoped by software revision: 180 bar applies before 3.2 and 200 bar from 3.2 - do not merge them.
(4) Lower trust_tier number = more authoritative (1 change notice, 2 official, 3 secondary, 4 low-trust/superseded, 5 irrelevant).
Never let a tier-4/5 passage override a tier 1-2 passage; mention contradictions in "conflicts".
(5) If the passages do not contain the answer, set status INSUFFICIENT_EVIDENCE and explain what is missing in "unknowns".
Return ONLY JSON: {"status": "ANSWERED|ANSWERED_WITH_CAVEATS|CONFLICT|INSUFFICIENT_EVIDENCE", "answer": str,
"claims": [{"text": str, "passage_ids": [str]}], "conflicts": [str], "unknowns": [str]}"""

_NUM = re.compile(r"(\d+(?:\.\d+)?)\s?(bar|seconds?|s\b|V\b|°\s?C)", re.I)


def build_prompt(question: str, hits, engine) -> str:
    parts = []
    for h in hits:
        p = h.passage
        parts.append(f"[{p['passage_id']}] source={p['rel_path']} trust_tier={p['authority_level']} "
                     f"doc_rev={p.get('doc_rev')} applies_to={p.get('applies_to')} loc={p.get('section_title')}\n{p['content']}")
    return "PASSAGES:\n" + "\n\n".join(parts) + f"\n\nQUESTION: {question}"


def default_client():
    import anthropic
    return anthropic.Anthropic()


def validate(data: dict, allowed_ids: set, passages_text: dict) -> Optional[str]:
    """Returns an error string, or None if the response is acceptable."""
    if data.get("status") not in (ANSWERED, CAVEATS, CONFLICT, INSUFFICIENT):
        return "invalid status"
    claims = data.get("claims") or []
    if data["status"] != INSUFFICIENT and not claims:
        return "no claims"
    cited_text = ""
    for c in claims:
        ids = c.get("passage_ids") or []
        if not ids:
            return "claim without citation"
        for i in ids:
            if i not in allowed_ids:
                return f"fabricated citation {i}"
            cited_text += " " + passages_text[i]
    norm = lambda s: re.sub(r"\bseconds?\b", "s", re.sub(r"\s+", " ", s), flags=re.I)
    ct = norm(cited_text)
    blob = norm(data.get("answer", "") + " " + " ".join(c.get("text", "") for c in claims))
    for n, u in _NUM.findall(blob):
        u = u.lower().replace("seconds", "s").replace("second", "s")
        if not re.search(re.escape(n) + r"\s?" + re.escape(u), ct, re.I):
            return f"ungrounded number {n} {u}"
    return None


def llm_answer(question: str, hits, engine, client=None) -> Optional[Answer]:
    if not hits:
        return None
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        client = default_client()
    try:
        msg = client.messages.create(model=config.LLM_MODEL, max_tokens=1000, system=SYSTEM,
                                     messages=[{"role": "user", "content": build_prompt(question, hits, engine)}])
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip())
    except Exception:
        return None
    allowed = {h.passage_id for h in hits}
    texts = {h.passage_id: h.passage["content"] for h in hits}
    err = validate(data, allowed, texts)
    if err:
        return Answer(question, f"The LLM draft was rejected by citation/number validation ({err}); no answer is given.", INSUFFICIENT, "n/a",
                      [], [], [f"LLM output rejected: {err}"], handler="llm_rejected")
    claims = [Claim(c["text"], [engine.ev(i) for i in c["passage_ids"]]) for c in data.get("claims", [])]
    return Answer(question, data.get("answer", ""), data["status"], "medium", claims, data.get("conflicts", []),
                  data.get("unknowns", []), ["Answer drafted by an LLM from retrieved passages; citations/numbers machine-validated, wording not."], handler="llm")
