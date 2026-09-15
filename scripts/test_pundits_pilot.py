#!/usr/bin/env python3
"""The P6 pilot: seeded sampling, certain automatic failures, human labels required, P5 caps, exact yield bounds.

Pundits plan, P6.

  BOUNDS      exact binomial bounds match closed forms: 24/24 lower-80 is 0.2**(1/24),
              0/12 upper-97.5 is 1-0.025**(1/12) (0.2646, the P4d figure)
  SAMPLE      the same seed gives the same draw, at most N per person
  DATES       a missing upload date fails loudly; the window edges are inclusive;
              an archival subject uses the 5 years before the last recording and
              fails an upload made after it
  SUBSTITUTE  "filling in for Ben" and "Ben is on vacation" in the opening fail;
              the same words late in the transcript do not
  GUEST-ONLY  a transcript that never names the subject is flagged for a person
  HUMAN       nothing is verified without a label; a missing or invalid label
              makes the gate INCONCLUSIVE; subject_present false is counted as
              wrong-person and never selected
  CAPS        at most 4 own-show recordings, at most 2 per external channel,
              at most 2 inside 7 days
  GATE        a person with fewer than 4 selectable recordings FAILs; all labelled
              and enough everywhere PASSes

No network, no quota.

  .venv/bin/python scripts/test_pundits_pilot.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
PASS, FAIL = [], []
OWN = "UC" + "o" * 22


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if not ok and detail else ""))


PERSON = {"slug": "ben-shapiro", "name": "Ben Shapiro", "handles": [], "archival": False,
          "own_channels": [{"channel_id": OWN}]}
KIRK = {"slug": "charlie-kirk", "name": "Charlie Kirk", "handles": ["RealCharlieKirk"], "archival": True,
        "last_recording_date": "2025-09-10", "own_channels": [{"channel_id": OWN}]}
FILLER = " ".join(["policy"] * 900)


def rec(upload="20240101", text=None):
    return {"yt_upload_date": upload, "text": text if text is not None else "Ben Shapiro here. " + FILLER}


def label(present=True, main=True, venue="guest_interview", political=True):
    # main_speaker is no longer a label (operator, 2026-09-15): presence means "enough
    # of the subject to be worth grading"; judges' share estimates filter the rest.
    return {"subject_present": present, "venue": venue, "political_content": political, "checked_by": "tester"}


def main() -> int:
    print("pundits pilot")
    import pundits_pilot as P

    print("\n[BOUNDS]")
    check("24/24 one-sided 80% lower bound is 0.2**(1/24)", abs(P.lower_bound(24, 24, 0.2) - 0.2 ** (1 / 24)) < 1e-6)
    check("0/12 upper 97.5% bound is 1-0.025**(1/12)", abs(P.upper_bound(0, 12, 0.025) - (1 - 0.025 ** (1 / 12))) < 1e-6)
    check("0 successes have lower bound 0 and n successes upper bound 1",
          P.lower_bound(0, 10, 0.2) == 0.0 and P.upper_bound(10, 10, 0.025) == 1.0)

    print("\n[SAMPLE]")
    disc = {"leaders": [{"leader_slug": "ben-shapiro", "sources": [
        {"video_id": f"v{i:010d}", "source_id": f"s{i}", "title": "t", "venue": "c", "kind": "podcast",
         "channel_id": OWN, "discovery_stratum": "own_channel"} for i in range(40)]}]}
    a, b, c = P.sample(disc, 24, 1), P.sample(disc, 24, 1), P.sample(disc, 24, 2)
    check("the same seed gives the same draw", a == b)
    check("a different seed gives a different draw", a != c)
    check("at most N per person, ranks 1..N", len(a) == 24 and [r["rank"] for r in a] == list(range(1, 25)))
    mixed = {"leaders": [{"leader_slug": "ben-shapiro", "sources": disc["leaders"][0]["sources"] + [
        {"video_id": f"x{i:010d}", "source_id": f"x{i}", "title": "t", "venue": "Other", "kind": "interview",
         "channel_id": "UC" + "e" * 22, "discovery_stratum": "interlocutor"} for i in range(5)]}]}
    d = P.sample(mixed, 24, 1)
    check("scarce other-channel candidates are all drawn before own-channel uploads fill the rest",
          sum(r["discovery_stratum"] == "interlocutor" for r in d) == 5 and len(d) == 24)
    many = {"leaders": [{"leader_slug": "ben-shapiro", "sources": [
        {"video_id": f"x{i:010d}", "source_id": f"x{i}", "title": "t", "venue": "Other", "kind": "interview",
         "channel_id": "UC" + "e" * 22, "discovery_stratum": "debate"} for i in range(30)] + disc["leaders"][0]["sources"]}]}
    d = P.sample(many, 24, 1)
    check("other-channel candidates take at most half the draw when own-channel uploads exist",
          sum(r["discovery_stratum"] == "debate" for r in d) == 12)

    print("\n[DATES]")
    check("a missing upload date fails", P.precheck({"text": "x"}, PERSON)[0] == "FAIL")
    check("the window start is inclusive", P.precheck(rec("20210913"), PERSON)[0] == "NEEDS_HUMAN")
    check("the window end is inclusive", P.precheck(rec("20260913"), PERSON)[0] == "NEEDS_HUMAN")
    check("a day before the window fails", P.precheck(rec("20210912"), PERSON)[0] == "FAIL")
    kirk_text = "Charlie Kirk here. " + FILLER
    check("an archival subject's window starts 5 years before the last recording",
          P.precheck(rec("20200910", kirk_text), KIRK)[0] == "NEEDS_HUMAN"
          and P.precheck(rec("20200909", kirk_text), KIRK)[0] == "FAIL")
    v, why = P.precheck(rec("20251001", kirk_text), KIRK)
    check("an archival upload after the last recording fails and says so", v == "FAIL" and "last recording" in why[0], str(why))

    print("\n[SUBSTITUTE]")
    v, why = P.precheck(rec(text="Hi everyone, I'm filling in for Ben today. " + FILLER), PERSON)
    check("'filling in for Ben' in the opening fails", v == "FAIL" and "substitute" in why[0], str(why))
    v, _ = P.precheck(rec(text="Welcome. Shapiro is on vacation this week. " + FILLER), PERSON)
    check("'Shapiro is on vacation' in the opening fails", v == "FAIL")
    v, _ = P.precheck(rec(text="Ben Shapiro here. " + FILLER + " next week Mark is filling in for Ben"), PERSON)
    check("the same words late in the transcript do not fail", v == "NEEDS_HUMAN")

    print("\n[GUEST-ONLY]")
    v, why = P.precheck(rec(text="Welcome to the show, today's guest is a historian. " + FILLER), PERSON)
    check("a transcript that never names the subject is flagged", v == "NEEDS_HUMAN" and any("never named" in w for w in why), str(why))

    print("\n[HUMAN]")
    roster = {"ben-shapiro": PERSON}

    def manifest(n, channel=OWN):
        return [{"leader_slug": "ben-shapiro", "source_id": f"s{i}", "video_id": f"v{i:010d}", "title": "t",
                 "venue": "c", "kind": "podcast", "channel_id": channel, "discovery_stratum": "own_channel"} for i in range(n)]

    def pcs(n, spacing=10):
        from datetime import date, timedelta
        return {f"ben-shapiro/s{i}": {"verdict": "NEEDS_HUMAN", "reasons": [],
                                      "upload": (date(2024, 1, 1) + timedelta(days=i * spacing)).strftime("%Y%m%d")}
                for i in range(n)}

    m = manifest(8)
    out = P.report(m, pcs(8), {}, roster, 1)
    check("with no labels the gate is INCONCLUSIVE and nothing is verified",
          out["gate"] == "INCONCLUSIVE" and out["people"]["ben-shapiro"]["verified"] == 0, out["why"])
    human = {f"ben-shapiro/s{i}": label() for i in range(8)}
    human["ben-shapiro/s0"] = {"subject_present": True}
    out = P.report(m, pcs(8), human, roster, 1)
    check("an invalid label makes the gate INCONCLUSIVE", out["gate"] == "INCONCLUSIVE" and out["invalid_labels"], out["why"])
    human["ben-shapiro/s0"] = label(present=False)
    out = P.report(m, pcs(8), human, roster, 1)
    check("subject_present false is counted as wrong-person and not verified",
          out["wrong_person_found"] == ["ben-shapiro/s0"] and out["people"]["ben-shapiro"]["verified"] == 7, str(out["people"]))

    print("\n[NO-CAPS]")
    # Operator decision 2026-09-15 (option b): no venue, channel, 7-day or count caps.
    # Every verified recording is graded; format is handled by recording the venue,
    # showing each person's mix, and adjusting only where the data support it.
    human = {f"ben-shapiro/s{i}": label(venue="own_show_monologue") for i in range(10)}
    out = P.report(manifest(10), pcs(10), human, roster, 1)
    check("all 10 own-show recordings are selected", out["people"]["ben-shapiro"]["selected"] == 10, str(out["people"]))
    check("the venue mix is reported per person",
          out["people"]["ben-shapiro"].get("venue_mix") == {"own_show_monologue": 10}, str(out["people"]))
    ext = "UC" + "e" * 22
    human = {f"ben-shapiro/s{i}": label() for i in range(10)}
    out = P.report(manifest(10, channel=ext), pcs(10), human, roster, 1)
    check("all 10 recordings from one outside channel are selected", out["people"]["ben-shapiro"]["selected"] == 10, str(out["people"]))
    human20 = {f"ben-shapiro/s{i}": label() for i in range(20)}
    out = P.report(manifest(20), pcs(20, spacing=1), human20, roster, 1)
    check("20 recordings uploaded on consecutive days are all selected, with no count cap",
          out["people"]["ben-shapiro"]["selected"] == 20, str(out["people"]["ben-shapiro"]["selected"]))

    print("\n[DISCLOSE]")
    # Model-drafted labels count toward the gate (operator, 2026-09-15), and the
    # report says how many verified recordings rest on a model draft.
    human = {f"ben-shapiro/s{i}": label() for i in range(8)}
    for i in (0, 1, 2):
        human[f"ben-shapiro/s{i}"] |= {"drafted_by_model": True, "checked_by": "model:claude-sonnet-5"}
    out = P.report(manifest(8), pcs(8), human, roster, 1)
    check("the report counts verified recordings that rest on a model draft, per person and overall",
          out["people"]["ben-shapiro"].get("verified_model_drafted") == 3 and out.get("model_drafted_verified") == 3,
          str({k: out.get(k) for k in ("model_drafted_verified",)} | {"person": out["people"]["ben-shapiro"].get("verified_model_drafted")}))

    print("\n[TOPIC]")
    # Operator decision 2026-09-15: a recording with no political content (for
    # example a gaming stream) is excluded, counted as off_topic, never as wrong-person.
    human = {f"ben-shapiro/s{i}": label() for i in range(8)}
    human["ben-shapiro/s0"] = label(political=False)
    out = P.report(manifest(8), pcs(8), human, roster, 1)
    p = out["people"]["ben-shapiro"]
    check("a recording with no political content is off_topic, not verified and not wrong-person",
          p["outcomes"].get("off_topic") == 1 and p["verified"] == 7 and not out["wrong_person_found"], str(p))
    human["ben-shapiro/s0"] = {k: v for k, v in label().items() if k != "political_content"}
    out = P.report(manifest(8), pcs(8), human, roster, 1)
    check("a label without political_content is invalid, so the gate is INCONCLUSIVE",
          out["gate"] == "INCONCLUSIVE" and out["invalid_labels"], out["why"])

    print("\n[GATE]")
    human = {f"ben-shapiro/s{i}": label() for i in range(3)}
    out = P.report(manifest(3), pcs(3), human, roster, 1)
    check("fewer than 4 selectable recordings FAILs", out["gate"] == "FAIL", out["why"])
    human = {f"ben-shapiro/s{i}": label() for i in range(12)}
    out = P.report(manifest(12), pcs(12), human, roster, 1)
    check("fully labelled with enough recordings PASSes", out["gate"] == "PASS", out["why"])
    check("the full-run candidate count follows ceil(12 / lower80) with a floor of 24",
          out["people"]["ben-shapiro"]["candidates_needed_full_run"] == 24, str(out["people"]))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("failed: " + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
