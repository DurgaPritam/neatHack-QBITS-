from app.scoring import compute_score

IDS = ["before_after", "failure_recovery", "neatlogs_sdk", "neatlogs_traces", "entire_checkpoints",
       "cfo_ai_plan", "demo_video", "commits_in_window", "public_posts", "readme_exists", "dead_links"]


def checks(status="pass", **over):
    out = [{"id": "repo_public", "title": "public", "status": "pass", "detail": ""},
           {"id": "prompt_injection", "title": "inj", "status": "pass", "detail": ""}]
    out += [{"id": i, "title": i, "status": over.get(i, status), "detail": ""} for i in IDS]
    return out


GOOD_EST = {"agent_quality": {"score": 10, "evidence": ["a.py:1"]}, "usefulness": {"score": 10, "evidence": ["x"]}}


def test_perfect_checks_but_estimates_are_capped():
    s = compute_score(checks(), estimates=GOOD_EST)
    # estimates are 0.30*30 + 0.5*10 = 14 points, capped at 80% -> lose 2.8
    assert s["score"] == 97 and s["estimated_points"] == 11.2


def test_all_fail_scores_low_and_fixes_are_sorted():
    s = compute_score(checks("fail"))
    assert s["score"] == 7  # only neutral estimates remain
    pts = [f["points"] for f in s["fix_candidates"]]
    assert pts == sorted(pts, reverse=True) and s["fix_candidates"][0]["check_id"] == "demo_video"


def test_private_repo_gates_score():
    c = checks()
    c[0]["status"] = "fail"
    s = compute_score(c, estimates=GOOD_EST)
    assert s["score"] == 0 and s["gated"] and s["fix_candidates"] == []


def test_estimate_without_evidence_capped_harder():
    s1 = compute_score(checks(), estimates={"agent_quality": {"score": 10, "evidence": []}})
    s2 = compute_score(checks(), estimates={"agent_quality": {"score": 10, "evidence": ["f:1"]}})
    assert s1["score"] < s2["score"]


def test_claims_feed_their_category():
    claims = [{"id": "c1", "category": "tools"}, {"id": "c2", "category": "tools"}]
    good = compute_score(checks(), claims, [{"claim_id": "c1", "status": "verified"},
                                            {"claim_id": "c2", "status": "verified"}])
    bad = compute_score(checks(), claims, [{"claim_id": "c1", "status": "contradicted"},
                                           {"claim_id": "c2", "status": "contradicted"}])
    assert good["score"] > bad["score"]


def test_injection_neutralises_estimates():
    s = compute_score(checks(), estimates=GOOD_EST, injection_detected=True)
    assert s["estimated_points"] == 7.0 and s["flags"]["prompt_injection"]


def test_not_scored_check_gives_its_weight_to_the_category():
    base = compute_score(checks(), estimates=GOOD_EST)
    c = checks()
    entire = next(x for x in c if x["id"] == "entire_checkpoints")
    entire.update(status="unverified", data={"not_scored": True})
    s = compute_score(c, estimates=GOOD_EST)
    assert s["score"] == base["score"]  # no deduction
    tools = next(cat for cat in s["categories"] if cat["id"] == "tools")
    row = next(r for r in tools["items"] if r["id"] == "entire_checkpoints")
    assert row["not_scored"] and row["max_points"] == 0
    assert all(f["check_id"] != "entire_checkpoints" for f in s["fix_candidates"])


def test_claim_rows_are_told_apart_per_category():
    from app.scoring import compute_score
    claims = [{"id": "c1", "category": "agent"}, {"id": "c2", "category": "tools"}]
    out = compute_score([], claims, [{"claim_id": "c1", "status": "unverified"},
                                     {"claim_id": "c2", "status": "unverified"}])
    titles = [f["title"] for f in out["fix_candidates"] if f["check_id"] == "claims"]
    assert len(titles) == 2 and len(set(titles)) == 2
