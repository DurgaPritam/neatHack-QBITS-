"""Deterministic scoring: rubric checks + claim results -> 0-100 score.

The LLM never sets the score. It only supplies:
- claim results (already filtered so "verified" needs evidence the agent actually saw)
- two estimates for things code can't measure (agent quality, usefulness), which are
  marked "estimated" and capped.

Eligibility checks don't award points: a repo judges can't open scores 0, and a
prompt-injection attempt is flagged but cannot move the score either way.
"""
from app.tools.rubric import WEIGHTS

CREDIT = {"pass": 1.0, "warn": 0.5, "unverified": 0.5, "fail": 0.0}
CLAIM_CREDIT = {"verified": 1.0, "unverified": 0.25, "contradicted": 0.0}

ESTIMATE_CAP = 0.8               # an LLM opinion alone can never earn full marks
ESTIMATE_CAP_NO_EVIDENCE = 0.3
ESTIMATE_NEUTRAL = 0.5           # used when the LLM is unavailable or the repo tried injection
CLAIMS_WEIGHT = 0.15             # share of a category given to its claims, when it has any

# category -> [(item_id, weight)]; "est:" items are LLM estimates.
ITEMS: dict[str, list[tuple[str, float]]] = {
    "agent": [("before_after", 0.35), ("failure_recovery", 0.35), ("est:agent_quality", 0.30)],
    "tools": [("neatlogs_sdk", 0.30), ("neatlogs_traces", 0.25),
              ("entire_checkpoints", 0.20), ("cfo_ai_plan", 0.25)],
    "demo_video": [("demo_video", 1.0)],
    "building_in_public": [("commits_in_window", 0.6), ("public_posts", 0.4)],
    "usefulness": [("readme_exists", 0.3), ("dead_links", 0.2), ("est:usefulness", 0.5)],
}
ELIGIBILITY = ("repo_public", "prompt_injection")


def estimate_credit(est: dict | None, injection_detected: bool) -> tuple[float, str]:
    if not est or not isinstance(est.get("score"), (int, float)):
        return ESTIMATE_NEUTRAL, "LLM estimate unavailable; neutral default"
    credit = max(0.0, min(float(est["score"]), 10.0)) / 10.0
    cap, why = ESTIMATE_CAP, f"LLM estimate {est['score']}/10 (capped at {ESTIMATE_CAP})"
    if not est.get("evidence"):
        cap, why = ESTIMATE_CAP_NO_EVIDENCE, f"LLM estimate {est['score']}/10 cited no evidence"
    if injection_detected:
        cap, why = ESTIMATE_NEUTRAL, "injection attempt detected; estimate held at neutral"
    return min(credit, cap), why


def compute_score(checks: list[dict], claims: list[dict] | None = None,
                  claim_results: list[dict] | None = None, estimates: dict | None = None,
                  injection_detected: bool = False) -> dict:
    by_id = {c["id"]: c for c in checks}
    claims = claims or []
    status_by_claim = {r["claim_id"]: r["status"] for r in (claim_results or [])}
    estimates = estimates or {}

    categories = []
    total = 0.0
    fix_candidates = []
    for cat, items in ITEMS.items():
        cat_max = WEIGHTS[cat] * 100
        cat_claims = [c for c in claims if c.get("category") == cat]
        # A check that couldn't be verified automatically and is marked not_scored gives its
        # weight to the rest of the category: no deduction for what we can't see.
        skipped = {i for i, _ in items if ((by_id.get(i) or {}).get("data") or {}).get("not_scored")}
        kept = sum(w for i, w in items if i not in skipped)
        weighted = [(i, w / (kept or 1)) for i, w in items if i not in skipped]
        if not weighted:
            # Nothing in this category could be checked (e.g. the demo video's length is unknown):
            # leave the whole category out and rescale the total below.
            rows = [{"id": i, "max_points": 0, "estimated": False, "title": by_id[i]["title"],
                     "status": by_id[i]["status"], "detail": by_id[i]["detail"], "credit": 0, "points": 0,
                     "not_scored": True} for i, _ in items]
            categories.append({"id": cat, "weight": WEIGHTS[cat], "max_points": 0, "points": 0,
                               "not_scored": True, "items": rows})
            continue
        if cat_claims:
            weighted = [(i, w * (1 - CLAIMS_WEIGHT)) for i, w in items] + [("claims", CLAIMS_WEIGHT)]
        rows = []
        for item_id, w in weighted:
            max_pts = cat_max * w
            row = {"id": item_id, "max_points": round(max_pts, 2), "estimated": False}
            if item_id.startswith("est:"):
                credit, why = estimate_credit(estimates.get(item_id[4:]), injection_detected)
                row.update(title=item_id[4:].replace("_", " "), status="estimated",
                           detail=why, estimated=True)
            elif item_id == "claims":
                vals = [CLAIM_CREDIT.get(status_by_claim.get(c["id"], "unverified"), 0.25) for c in cat_claims]
                credit = sum(vals) / len(vals)
                counts = {s: sum(1 for c in cat_claims if status_by_claim.get(c["id"], "unverified") == s)
                          for s in CLAIM_CREDIT}
                row.update(title="README claims backed by evidence", status="claims",
                           detail=", ".join(f"{n} {s}" for s, n in counts.items() if n))
            else:
                chk = by_id.get(item_id)
                status = chk["status"] if chk else "unverified"
                credit = CREDIT[status]
                row.update(title=chk["title"] if chk else item_id, status=status,
                           detail=chk["detail"] if chk else "check not run")
            row["credit"] = round(credit, 3)
            row["points"] = round(max_pts * credit, 2)
            rows.append(row)
            gain = max_pts - row["points"]
            if gain > 0.05 and not row["estimated"]:
                fix_candidates.append({"check_id": item_id, "category": cat, "title": row["title"],
                                       "detail": row["detail"], "points": round(gain, 1)})
        for item_id in skipped:
            chk = by_id[item_id]
            rows.append({"id": item_id, "max_points": 0, "estimated": False, "title": chk["title"],
                         "status": chk["status"], "detail": chk["detail"], "credit": 0, "points": 0,
                         "not_scored": True})
        pts = sum(r["points"] for r in rows)
        total += pts
        categories.append({"id": cat, "weight": WEIGHTS[cat], "max_points": cat_max,
                           "points": round(pts, 1), "items": rows})

    scored_max = sum(c["max_points"] for c in categories)
    if 0 < scored_max < 100:
        total = total * 100 / scored_max
    repo_check = by_id.get("repo_public")
    gated = bool(repo_check and repo_check["status"] == "fail")
    estimated_points = sum(r["points"] for c in categories for r in c["items"] if r["estimated"])
    fix_candidates.sort(key=lambda f: -f["points"])
    return {
        "score": 0 if gated else int(round(total)),
        "max": 100,
        "gated": gated,
        "gate_reason": repo_check["detail"] if gated else None,
        "estimated_points": round(estimated_points, 1),
        "scored_max": round(scored_max, 1),   # < 100 when a whole category couldn't be checked
        "categories": categories,
        "fix_candidates": [] if gated else fix_candidates,
        "flags": {"prompt_injection": injection_detected},
    }
