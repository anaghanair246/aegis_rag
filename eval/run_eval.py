"""Reproducible evaluation. Usage: python -m eval.run_eval [--db data/aegis_rag.db] [--out eval/results]
All numbers are measured here; nothing is hard-coded. Automated checks only (regex/gold-passage based);
there is NO human or LLM-judge scoring in this script."""
import argparse, json, math, re, statistics, time
from src.database import DatabaseManager
from src.retrieval.index import HybridIndex
from src.qa.engine import QAEngine
from src.qa.models import INSUFFICIENT

CONFIGS = {
    "bm25": dict(mode="bm25", expand_aliases=False, rerank=False, dedupe=False),
    "tfidf": dict(mode="tfidf", expand_aliases=False, rerank=False, dedupe=False),
    "hybrid": dict(mode="hybrid", expand_aliases=False, rerank=False, dedupe=False),
    "hybrid+alias": dict(mode="hybrid", expand_aliases=True, rerank=False, dedupe=False),
    "hybrid+alias+rerank+dedupe (default)": dict(mode="hybrid", expand_aliases=True, rerank=True, dedupe=True),
}
UNIT_NUM = re.compile(r"(\d+(?:\.\d+)?)\s?(bar|seconds?|s\b|V\b|°\s?C)", re.I)


def resolve_gold(db, specs):
    ids, unresolved = set(), []
    with db.conn() as c:
        rows = c.execute("SELECT p.passage_id, p.content, d.rel_path FROM passages p JOIN documents d USING(doc_id)").fetchall()
    for s in specs:
        m = [r["passage_id"] for r in rows if r["rel_path"].endswith(s["doc"]) and re.search(s["contains"], re.sub(r"\s+", " ", r["content"]), re.I)]
        if m: ids.update(m)
        else: unresolved.append(s)
    return ids, unresolved


def retrieval_metrics(index, qs, db, k):
    res = {}
    for name, cfg in CONFIGS.items():
        P, R, H, MRR, NDCG, lat = [], [], [], [], [], []
        for q in qs:
            gold, _ = resolve_gold(db, q["gold"])
            if not gold: continue
            t = time.time(); hits = index.search(q["text"], k=k, **cfg); lat.append((time.time() - t) * 1000)
            rel = [1 if h.passage_id in gold else 0 for h in hits]
            P.append(sum(rel) / k); R.append(len({h.passage_id for h in hits} & gold) / len(gold)); H.append(1.0 if any(rel) else 0.0)
            MRR.append(next((1 / (i + 1) for i, r in enumerate(rel) if r), 0.0))
            dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel)); idcg = sum(1 / math.log2(i + 2) for i in range(min(len(gold), k)))
            NDCG.append(dcg / idcg if idcg else 0.0)
        mean = lambda x: round(sum(x) / len(x), 3) if x else None
        res[name] = {f"P@{k}": mean(P), f"R@{k}": mean(R), f"Hit@{k}": mean(H), "MRR": mean(MRR), f"nDCG@{k}": mean(NDCG),
                     "retrieval_ms_mean": round(statistics.mean(lat), 2), "n_questions": len(P)}
    return res


def corpus(a):
    return " \n".join([a.answer] + [c.text for c in a.claims] + a.conflicts + a.unknowns + a.assumptions)


def answer_eval(engine, qs):
    rows = []
    for q in qs:
        a = engine.ask(q["text"])
        text = corpus(a)
        status_ok = a.status in q["expected_status"]
        facts_ok = all(re.search(p, text, re.I | re.S) for p in q["must_contain"])
        cited_docs = {e.source for c in a.claims for e in c.evidence}
        req_cites = q["must_cite"]
        cite_recall = (sum(any(d.endswith(r) for d in cited_docs) for r in req_cites) / len(req_cites)) if req_cites else None
        gold_docs = set(req_cites) | {g["doc"] for g in q["gold"]}
        cite_prec = (sum(any(d.endswith(g) for g in gold_docs) for d in cited_docs) / len(cited_docs)) if cited_docs and gold_docs else None
        pids = {e.passage_id for c in a.claims for e in c.evidence}
        with engine.db.conn() as c:
            ev_text = " ".join(r[0] for pid in pids for r in c.execute("SELECT content FROM passages WHERE passage_id=?", (pid,)))
        ev_text = re.sub(r"_(bar|seconds|s) = (\d+(?:\.\d+)?)", r" \2 \1", ev_text)
        ev_text = re.sub(r"\b(\d\d):(\d\d):(\d\d)\b", lambda m: f"{m.group(0)} {int(m.group(1))*3600+int(m.group(2))*60+int(m.group(3))} s", ev_text)  # hh:mm:ss durations -> seconds  # JSON keys carry the unit in their suffix
        ev_norm = re.sub(r"\bseconds?\b", "s", re.sub(r"\s+", " ", ev_text), flags=re.I)
        q_nums = {(n, u.lower().replace("seconds", "s").replace("second", "s").replace(" ", "")) for n, u in UNIT_NUM.findall(q["text"])}
        nums = {(n, u.lower().replace("seconds", "s").replace("second", "s").replace(" ", "")) for n, u in UNIT_NUM.findall(text)} - q_nums  # numbers echoed from the question are not fabricated facts
        ungrounded = [f"{n} {u}" for n, u in nums if not re.search(re.escape(n) + r"\s?" + re.escape(u.replace("°c", "°")).replace("°", "°\\s?") , ev_norm, re.I)
                      and not re.search(re.escape(n) + r"\s?" + re.escape(u), ev_norm, re.I)]
        halluc = bool([p for p in q["forbid"] if re.search(p, text, re.I)]) or bool(ungrounded)
        unsupported_claims = sum(1 for c in a.claims if not c.evidence)
        rows.append(dict(id=q["id"], set=q["set"], category=q["category"], expected=q["expected_status"], status=a.status, status_ok=status_ok,
                         facts_ok=facts_ok, cite_recall=cite_recall, cite_precision=cite_prec, n_claims=len(a.claims),
                         unsupported_claims=unsupported_claims, ungrounded_numbers=ungrounded, hallucination=halluc,
                         correct=status_ok and facts_ok and not halluc, handler=a.handler, confidence=a.confidence,
                         flags=dict(conflicts=len(a.conflicts), unknowns=len(a.unknowns), assumptions=len(a.assumptions)),
                         ms=a.timings_ms, answer=a.answer[:300]))
    return rows


def summarise(rows):
    n = len(rows)
    if not n: return {}
    f = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    un = [r for r in rows if r["expected"] == [INSUFFICIENT]]
    ans = [r for r in rows if r["expected"] != [INSUFFICIENT]]
    tp = sum(1 for r in un if r["status"] == INSUFFICIENT); fp = sum(1 for r in ans if r["status"] == INSUFFICIENT)
    tot = [r["ms"]["total"] for r in rows]
    return {"n": n, "end_to_end_correct": f([r["correct"] for r in rows]),
            "status_accuracy": f([r["status_ok"] for r in rows]),
            "key_fact_recall(answerable)": f([r["facts_ok"] for r in ans]),
            "citation_required_doc_recall": f([r["cite_recall"] for r in rows if r["cite_recall"] is not None]),
            "citation_doc_precision": f([r["cite_precision"] for r in rows if r["cite_precision"] is not None]),
            "unsupported_claim_rate": f([r["unsupported_claims"] / r["n_claims"] for r in rows if r["n_claims"]]),
            "hallucination_rate": f([r["hallucination"] for r in rows]),
            "abstention_recall(unanswerable)": f([r["status"] == INSUFFICIENT for r in un]),
            "abstention_precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "false_abstentions(answerable)": fp,
            "latency_total_ms_p50": round(statistics.median(tot), 1), "latency_total_ms_max": round(max(tot), 1),
            "latency_retrieval_ms_mean": round(statistics.mean(r["ms"]["retrieval"] for r in rows), 1)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", default="data/aegis_rag.db"); ap.add_argument("--out", default="eval/results")
    ap.add_argument("--k", type=int, default=5); args = ap.parse_args()
    db = DatabaseManager(args.db); index = HybridIndex(db); engine = QAEngine(db, index)
    qs = json.load(open("eval/questions.json"))
    unresolved = {q["id"]: resolve_gold(db, q["gold"])[1] for q in qs if resolve_gold(db, q["gold"])[1]}
    dev = [q for q in qs if q["set"] == "dev"]; para = [q for q in qs if q["set"] == "para"]; held = [q for q in qs if q["set"] == "held"]; scr = [q for q in qs if q["set"] == "scr"]; alarm = [q for q in qs if q["set"] == "alarm"]
    rows = answer_eval(engine, qs)
    with db.conn() as c:
        ing = json.loads(c.execute("SELECT stats FROM ingestion_runs ORDER BY run_id DESC LIMIT 1").fetchone()[0])
    out = {"retrieval_dev": retrieval_metrics(index, dev, db, args.k), "retrieval_para": retrieval_metrics(index, para, db, args.k), "retrieval_held": retrieval_metrics(index, held, db, args.k), "retrieval_scr": retrieval_metrics(index, scr, db, args.k), "retrieval_alarm": retrieval_metrics(index, alarm, db, args.k),
           "answers_dev": summarise([r for r in rows if r["set"] == "dev"]), "answers_para": summarise([r for r in rows if r["set"] == "para"]), "answers_held": summarise([r for r in rows if r["set"] == "held"]), "answers_scr": summarise([r for r in rows if r["set"] == "scr"]), "answers_alarm": summarise([r for r in rows if r["set"] == "alarm"]),
           "ingestion": {k: ing[k] for k in ("total_seconds", "ingest_seconds", "knowledge_seconds", "documents", "passages")},
           "unresolved_gold": unresolved, "per_question": rows}
    json.dump(out, open(args.out + ".json", "w"), indent=1, default=str)
    L = ["# Evaluation results (auto-generated, measured)\n", f"Ingestion: {out['ingestion']}\n"]
    for key in ("retrieval_dev", "retrieval_para", "retrieval_held", "retrieval_scr", "retrieval_alarm"):
        L.append(f"\n## {key}\n\n| config | " + " | ".join(next(iter(out[key].values())).keys()) + " |\n|" + "---|" * (len(next(iter(out[key].values()))) + 1))
        for n, m in out[key].items(): L.append(f"| {n} | " + " | ".join(str(v) for v in m.values()) + " |")
    for key in ("answers_dev", "answers_para", "answers_held", "answers_scr", "answers_alarm"):
        L.append(f"\n## {key}\n"); L += [f"- {k}: **{v}**" for k, v in out[key].items()]
    L.append("\n## Per-question\n\n| id | set | expected | got | facts | correct | handler | ungrounded nums |\n|---|---|---|---|---|---|---|---|")
    for r in rows: L.append(f"| {r['id']} | {r['set']} | {'/'.join(x[:6] for x in r['expected'])} | {r['status'][:9]} | {r['facts_ok']} | {r['correct']} | {r['handler']} | {r['ungrounded_numbers']} |")
    open(args.out + ".md", "w").write("\n".join(L)); print("\n".join(L[:60])); print("unresolved gold:", unresolved)


if __name__ == "__main__":
    main()
