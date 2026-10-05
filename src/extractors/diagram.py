"""Vector-diagram topology recovery (deterministic, no OCR/vision model).
Shapes = rounded-rect curves/rects; labels = text inside shape bbox; connectors = line objects whose
endpoints touch shapes; connector kind = stroke colour mapped through the drawing's own legend."""
import re
from typing import Dict, List, Tuple

COLOR_NAMES = {"purple": (0.54, 0.29, 0.61), "grey": (0.33, 0.33, 0.33), "tan": (0.69, 0.54, 0.31),
               "red": (0.8, 0.1, 0.1), "blue": (0.1, 0.2, 0.8), "green": (0.1, 0.6, 0.2)}


def _color_name(rgb) -> str:
    if not rgb or len(rgb) != 3:
        return "unknown"
    best = min(COLOR_NAMES, key=lambda n: sum((a - b) ** 2 for a, b in zip(rgb, COLOR_NAMES[n])))
    d = sum((a - b) ** 2 for a, b in zip(rgb, COLOR_NAMES[best]))
    return best if d < 0.05 else "unknown"


def parse_legend(text: str) -> Dict[str, str]:
    leg = {}
    for m in re.finditer(r"(\w+) lines?:\s*([^\n—]+)", text):
        leg[m.group(1).lower()] = m.group(2).strip()
    return leg


def _shape_bboxes(page) -> List[Tuple[float, float, float, float]]:
    boxes = []
    for o in list(page.curves) + list(page.rects):
        w, h = o["x1"] - o["x0"], o["bottom"] - o["top"]
        if w > 40 and h > 20:
            boxes.append((o["x0"], o["top"], o["x1"], o["bottom"]))
    return boxes


def _nearest(box_list, pt, tol=6.0):
    x, y = pt
    best, bd = None, 1e9
    for i, (x0, t, x1, b) in enumerate(box_list):
        dx = max(x0 - x, 0, x - x1)
        dy = max(t - y, 0, y - b)
        d = (dx * dx + dy * dy) ** 0.5
        if d < bd:
            best, bd = i, d
    return best if bd <= tol else None


def extract_topology(page):
    """Returns (nodes, edges, legend). Returns ([], [], {}) if the page has no diagram geometry."""
    boxes = _shape_bboxes(page)
    if len(boxes) < 3 or len(page.lines) < 2:
        return [], [], {}
    labels = []
    for (x0, t, x1, b) in boxes:
        txt = page.crop((x0, t, x1, b)).extract_text() or ""
        labels.append(" ".join(txt.split()))
    keep = [i for i, l in enumerate(labels) if 0 < len(l) <= 60]  # table cells / paragraphs are not diagram nodes
    if len(keep) < 3:
        return [], [], {}
    legend = parse_legend(page.extract_text() or "")
    edges = []
    for ln in page.lines:
        pts = ln.get("pts") or [(ln["x0"], ln["top"]), (ln["x1"], ln["bottom"])]
        a, b = _nearest(boxes, pts[0]), _nearest(boxes, pts[-1])
        if a is None or b is None or a == b or a not in keep or b not in keep:
            continue
        col = _color_name(ln.get("stroking_color"))
        edges.append({"a": labels[a], "b": labels[b], "color": col, "meaning": legend.get(col, "unspecified in legend")})
    # Deduplicate: a purple line plus a collinear grey stub can duplicate a node pair (kept distinct by colour).
    seen, uniq = set(), []
    for e in edges:
        k = (frozenset((e["a"], e["b"])), e["color"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return labels, uniq, legend
