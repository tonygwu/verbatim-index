#!/usr/bin/env python3
"""Generate the golden-eval fixtures: four synthetic caption-style transcripts and their gold labels.

The transcripts are written here, not copied from the corpus, because the
corpus is private and because the eval needs cases the corpus may lack (an
explicit "70% chance", a joke beside a real forecast, a quote that spans a
timestamp mark). They imitate the corpus: no speaker labels, filler, a mark
roughly every 150 words, one [Music] token, a corrupted proper noun,
interviewer questions running into answers, and the record shape of
data/transcripts_open including a hardcoded declared_year of 2024 that
nothing may read. One transcript has no upload date on purpose.

Every gold quote is checked to ground exactly in its transcript before
anything is written, so a typo here fails loudly instead of silently
lowering recall.

  .venv/bin/python scripts/fixtures/predictions/build_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import predictions_lib as L  # noqa: E402

ROSTER = [
    {"slug": "nova-reyes", "name": "Nova Reyes", "role": "CEO, Helix Compute", "company": "Helix Compute", "sector": "AI infrastructure"},
    {"slug": "dev-okafor", "name": "Dev Okafor", "role": "CEO, Lumen Robotics", "company": "Lumen Robotics", "sector": "Robotics"},
    {"slug": "mara-lindqvist", "name": "Mara Lindqvist", "role": "CEO, Northwind Payments", "company": "Northwind Payments", "sector": "Fintech"},
    {"slug": "kenji-sato", "name": "Kenji Sato", "role": "CTO, Orbital Foundry", "company": "Orbital Foundry", "sector": "Space"},
]

# ---------------------------------------------------------------------------
# podcast-01: Nova Reyes, upload 2025-01-15. Interviewer and subject run together.
# ---------------------------------------------------------------------------
PODCAST = """[00:00:00] welcome back to the show today we have Nova Reyes who runs Helix Compute thanks for coming on thanks for having me it's great to be here so let's start with the obvious question everybody is asking where does all this capacity go I mean we are seeing enormous demand for inference right now honestly more than we can serve and that's the thing people don't quite get about this cycle it's not training anymore it's serving so what does that look like in numbers well I think by the end of 2026 we will see 30 gigawatts of new data center capacity come online in the US and that is a conservative read the announced projects alone get you most of the way there [00:01:00] okay and the models themselves do they keep getting better at the same pace this is where I'll go out on a limb I'd put a 70% chance that a model passes a full bar exam blind by the end of next year not with retrieval not with tools blind and people will say that already happened and no it did not not under those conditions so you're saying by 2030 nobody writes code by hand yeah I mean that's fair I think that's roughly right although I'd phrase it differently [00:02:00] the cost side is the part I'm most sure about I'm almost certain that inference costs fall by another 10x over the next two years the hardware roadmap alone gets you 4x and the rest is software what could stop it I mean it's possible that we see a real slowdown in scaling who knows nobody actually knows that and anyone who says they do is selling something [Music] let's talk about your own roadmap what's coming we will ship our second generation chip to customers by June that is locked the tape out was in November and we have the Hellix two silicon back already [00:03:00] and after that you'll all be replaced by toasters ha ha no seriously the toaster thing is a joke we are not doing toasters what I actually want to say is we want to build the most reliable inference platform anyone has used and that is what the team is focused on every single day last question what did you get wrong last year I thought open models would stall and they did not they kept pace and I was wrong about that so I've stopped making that call thanks Nova thank you"""

PODCAST_GOLD = {
    "positives": [
        {"gold_id": "P1", "quote": "I think by the end of 2026 we will see 30 gigawatts of new data center capacity come online in the US",
         "horizon": "explicit", "target_date": "2026-12-31", "confidence_type": "none", "probability": None,
         "category": "technology_product", "prediction_type": "numeric", "subject_control": "external",
         "must_contain": ["30", "gigawatt", "2026"]},
        {"gold_id": "P2", "quote": "I'd put a 70% chance that a model passes a full bar exam blind by the end of next year",
         "horizon": "explicit", "target_date": "2026-12-31", "confidence_type": "explicit_probability", "probability": 0.7,
         "category": "ai_capability", "prediction_type": "milestone", "subject_control": "external",
         "must_contain": ["bar exam", "2026"]},
        {"gold_id": "P3", "quote": "I'm almost certain that inference costs fall by another 10x over the next two years",
         "horizon": "explicit", "target_date": "2027-01", "confidence_type": "qualitative", "probability": None,
         "category": "technology_product", "prediction_type": "numeric", "subject_control": "external",
         "must_contain": ["10x", "inference"]},
        {"gold_id": "P4", "quote": "we will ship our second generation chip to customers by June",
         "horizon": "explicit", "target_date": "2025-06", "confidence_type": "none", "probability": None,
         "category": "company_business", "prediction_type": "binary_event", "subject_control": "own",
         "must_contain": ["chip", "June"]},
    ],
    "negatives": [
        {"quote": "we are seeing enormous demand for inference right now", "reason": "current_state"},
        {"quote": "so you're saying by 2030 nobody writes code by hand yeah I mean that's fair", "reason": "interviewer_prediction"},
        {"quote": "it's possible that we see a real slowdown in scaling who knows", "reason": "hedged"},
        {"quote": "you'll all be replaced by toasters ha ha no seriously", "reason": "joke"},
        {"quote": "we want to build the most reliable inference platform anyone has used", "reason": "aspiration"},
        {"quote": "I thought open models would stall and they did not", "reason": "historical"},
    ],
}

# ---------------------------------------------------------------------------
# keynote-01: Dev Okafor, upload 2024-09-20. A keynote, mostly monologue, with a Q and A tail.
# ---------------------------------------------------------------------------
KEYNOTE = """[00:00:00] good morning everyone thank you for being here five years ago nobody believed a robot could walk on ice and now you have seen it on this stage twice so let me tell you where this goes our vision is that every home has a robot and the robot understands you that is the north star and it does not change but I want to be concrete because concrete is what you can hold me to a humanoid robot will be doing useful work in a real factory shift by the end of 2025 that is going to happen not a demo a shift with a badge and a supervisor [00:01:00] and here is my actual bet by 2028 the cost of a humanoid robot will be under 20,000 dollars and most of them will be built outside the United States I know that second part is unpopular in this room the macro picture helps us interest rates will be substantially lower by the end of next year than they are today and that changes the math on every capex decision our customers make everyone thinks robot demos are hype and I'm quite sure that within three years half of new warehouses will open with robot picking as the default not as a pilot [00:02:00] [Music] we are going to be the most trusted robotics company in the world that is a promise to every customer in this room and we want to build the safest robot ever made period now questions yes in the back thanks so when do you think a robot beats a human at folding laundry honestly I don't know and I'm not going to guess on stage what I will say is that if regulators required a remote kill switch on every unit you could see the whole market slow by a year but I don't expect that rule and last one your competitor Lumnn Dynamics says they'll be at a million units by 2027 that's their number not mine I'll let them defend it thank you all"""

KEYNOTE_GOLD = {
    "positives": [
        {"gold_id": "P5", "quote": "a humanoid robot will be doing useful work in a real factory shift by the end of 2025 that is going to happen",
         "horizon": "explicit", "target_date": "2025-12-31", "confidence_type": "none", "probability": None,
         "category": "technology_product", "prediction_type": "milestone", "subject_control": "partial",
         "must_contain": ["humanoid", "factory", "2025"]},
        {"gold_id": "P6", "quote": "interest rates will be substantially lower by the end of next year than they are today",
         "horizon": "explicit", "target_date": "2025-12-31", "confidence_type": "none", "probability": None,
         "category": "macro_economy", "prediction_type": "trend_direction", "subject_control": "external",
         "must_contain": ["interest rate", "lower", "2025"]},
        {"gold_id": "P7", "quote": "I'm quite sure that within three years half of new warehouses will open with robot picking as the default",
         "horizon": "explicit", "target_date": "2027-09", "confidence_type": "qualitative", "probability": None,
         "category": "market_industry", "prediction_type": "numeric", "subject_control": "external",
         "must_contain": ["half", "warehouse", "robot"]},
        {"gold_id": "P8", "quote": "here is my actual bet by 2028 the cost of a humanoid robot will be under 20,000 dollars and most of them will be built outside the United States",
         "horizon": "explicit", "target_date": "2028", "confidence_type": "qualitative", "probability": None,
         "category": "technology_product", "prediction_type": "numeric", "subject_control": "external",
         "must_contain": ["20,000", "2028"]},
    ],
    "negatives": [
        {"quote": "five years ago nobody believed a robot could walk on ice", "reason": "historical"},
        {"quote": "our vision is that every home has a robot and the robot understands you", "reason": "present_tense_vision"},
        {"quote": "we are going to be the most trusted robotics company in the world", "reason": "confident_grammar_no_test"},
        {"quote": "we want to build the safest robot ever made", "reason": "aspiration"},
        {"quote": "if regulators required a remote kill switch on every unit you could see the whole market slow by a year", "reason": "hypothetical"},
        {"quote": "Lumnn Dynamics says they'll be at a million units by 2027 that's their number not mine", "reason": "quoted_third_party"},
    ],
}

# ---------------------------------------------------------------------------
# interview-01: Mara Lindqvist, upload 2023-06-10. Undated forecast, business guidance, many negatives.
# ---------------------------------------------------------------------------
INTERVIEW = """[00:00:00] Mara thanks for sitting down with us let's talk about where payments are going you've been loud about this yes I have stablecoin settlement will overtake card networks for cross border business payments I have no doubt about it the unit economics are not close and merchants are not sentimental about rails will anyone still carry a plastic card in 2040 I mean think about that for a second the analysts at Bernstein think card volumes double by 2030 but that is their model not mine I don't publish a volume model [00:01:00] what about your own numbers our revenue will pass 2 billion this year we said that in the last letter and nothing has changed and if the regulators banned stablecoins tomorrow you could see volumes collapse overnight but that is a thought experiment not a forecast I'm pretty optimistic that things will improve for merchants generally the tooling is getting better people ask where you'll be in a decade thirteen years from now I'll still be at this company I really believe that [00:02:00] [Music] the gap between the banked and the unbanked will be more polarized that's the sad part and honestly when I look at the founders coming up now I'm pretty certain that you will be too the question is only when what's one thing you've changed your mind on I used to think Swiftt would be dead by now and it's clearly still there so I don't make that prediction anymore thanks Mara thank you"""

INTERVIEW_GOLD = {
    "positives": [
        {"gold_id": "P9", "quote": "stablecoin settlement will overtake card networks for cross border business payments I have no doubt about it",
         "horizon": "none", "target_date": None, "confidence_type": "qualitative", "probability": None,
         "category": "market_industry", "prediction_type": "trend_direction", "subject_control": "external",
         "must_contain": ["stablecoin", "card"]},
        {"gold_id": "P10", "quote": "our revenue will pass 2 billion this year",
         "horizon": "explicit", "target_date": "2023-12-31", "confidence_type": "none", "probability": None,
         "category": "company_business", "prediction_type": "numeric", "subject_control": "own",
         "must_contain": ["2 billion", "2023"]},
    ],
    "negatives": [
        {"quote": "will anyone still carry a plastic card in 2040", "reason": "rhetorical"},
        {"quote": "the analysts at Bernstein think card volumes double by 2030 but that is their model not mine", "reason": "quoted_third_party"},
        {"quote": "if the regulators banned stablecoins tomorrow you could see volumes collapse overnight", "reason": "hypothetical"},
        {"quote": "I'm pretty optimistic that things will improve for merchants generally", "reason": "vague_optimism"},
        {"quote": "thirteen years from now I'll still be at this company I really believe that", "reason": "personal_plan"},
        {"quote": "the gap between the banked and the unbanked will be more polarized", "reason": "non_falsifiable"},
        {"quote": "I'm pretty certain that you will be too", "reason": "dangling_quote"},
        {"quote": "I used to think Swiftt would be dead by now and it's clearly still there", "reason": "historical"},
    ],
}

# ---------------------------------------------------------------------------
# fireside-01: Kenji Sato, NO upload date. The interviewer proposes a number the subject rejects.
# The restatement of the 500-dollar claim 300 words later is deliberately NOT gold: the spec tells the
# extractor never to return the same claim twice, so a second record there is neither hit nor miss.
# ---------------------------------------------------------------------------
FIRESIDE = """[00:00:00] we're here with Kenji Sato of Orbital Foundry Kenji you've been building this for a decade right now we have about 200 engineers and most of them are on the depot program so let's get into the numbers everybody wants launch costs go to 100 dollars a kilo by 2030 right no I don't think that what I do think is that by 2030 launch cost to low earth orbit will be under 500 dollars a kilogram for a commercial customer buying a full manifest and that is already a huge deal a 100 dollar number needs full reuse of every stage and a flight rate nobody has [00:01:00] what does the depot timeline look like the first commercial [00:02:00] orbital fuel depot will be operating before the end of 2027 we have the customer we have the manifest and the long pole is a valve that we are testing this quarter people keep asking about Mars I'll say what I always say I don't know and I'm not going to put a date on it what about your competitors the ones with the big rockets could be at the depot before you sure maybe possibly I mean anything could happen in this industry [Music] [00:03:00] let me come back to cost because I want to be precise like I said under 500 dollars a kilo by 2030 that is the number and I'm happy to be held to it and one more thing the whole small launcher category is going to consolidate down to two or three players by the end of 2026 the economics don't support twelve thanks Kenji thanks"""

FIRESIDE_GOLD = {
    "positives": [
        {"gold_id": "P11", "quote": "by 2030 launch cost to low earth orbit will be under 500 dollars a kilogram for a commercial customer buying a full manifest",
         "horizon": "explicit", "target_date": "2030", "confidence_type": "none", "probability": None,
         "category": "technology_product", "prediction_type": "numeric", "subject_control": "partial",
         "must_contain": ["500", "2030"]},
        {"gold_id": "P13", "quote": "the first commercial [00:02:00] orbital fuel depot will be operating before the end of 2027",
         "horizon": "explicit", "target_date": "2027-12-31", "confidence_type": "none", "probability": None,
         "category": "technology_product", "prediction_type": "milestone", "subject_control": "own",
         "must_contain": ["depot", "2027"]},
        {"gold_id": "P14", "quote": "the whole small launcher category is going to consolidate down to two or three players by the end of 2026",
         "horizon": "explicit", "target_date": "2026-12-31", "confidence_type": "none", "probability": None,
         "category": "market_industry", "prediction_type": "numeric", "subject_control": "external",
         "must_contain": ["launcher", "2026"]},
    ],
    "negatives": [
        {"quote": "right now we have about 200 engineers", "reason": "current_state"},
        {"quote": "launch costs go to 100 dollars a kilo by 2030 right no I don't think that", "reason": "interviewer_prediction"},
        {"quote": "I don't know and I'm not going to put a date on it", "reason": "non_falsifiable"},
        {"quote": "sure maybe possibly I mean anything could happen in this industry", "reason": "hedged"},
    ],
}


def record(slug: str, sid: str, text: str, upload: str | None, title: str, venue: str, kind: str, video: str | None) -> dict:
    words = len(text.split())
    rec = {"leader_slug": slug, "source_id": sid, "video_id": video,
           "url": f"https://www.youtube.com/watch?v={video}" if video else f"https://podcasts.example.org/{sid}",
           "declared_title": title, "declared_venue": venue, "declared_kind": kind, "declared_year": 2024,
           "caption_track": "auto", "word_count": words, "char_count": len(text), "duration_sec": 60 * (text.count("[0") + 1),
           "n_timestamp_marks": len(L.MARK_RE.findall(text)), "fetched_at_utc": "2026-09-10T00:00:00Z",
           "fetch_method": "youtube_transcript_api" if video else "happyscribe", "yt_title": title if video else None,
           "yt_channel": venue if video else None, "yt_description": None, "text": text,
           "normalization": {"mode": "open", "fixture": True}}
    if upload:
        rec["yt_upload_date"] = upload
    return rec


FIXTURES = [
    ("nova-reyes", "podcast-01", PODCAST, PODCAST_GOLD, "20250115", "Nova Reyes on the inference build-out", "Compute Weekly", "podcast", "fixNova01"),
    ("dev-okafor", "keynote-01", KEYNOTE, KEYNOTE_GOLD, "20240920", "Lumen Robotics keynote 2024", "Lumen Robotics", "keynote", "fixDev001"),
    ("mara-lindqvist", "interview-01", INTERVIEW, INTERVIEW_GOLD, "20230610", "Mara Lindqvist on payment rails", "Fintech Hour", "tv_interview", "fixMara01"),
    ("kenji-sato", "fireside-01", FIRESIDE, FIRESIDE_GOLD, None, "Fireside with Kenji Sato", "Space Founders", "fireside_chat", None),
]


def main() -> int:
    problems = []
    for slug, sid, text, gold, upload, title, venue, kind, video in FIXTURES:
        for entry in gold["positives"] + gold["negatives"]:
            loc = L.locate_quote(text, entry["quote"])
            if "error" in loc:
                problems.append(f"{slug}/{sid}: {entry.get('gold_id') or entry['reason']}: {loc['error']}: {entry['quote'][:60]}")
                continue
            entry["char_start"], entry["char_end"] = loc["start"], loc["end"]
            wc = L.quote_word_count(text[loc["start"]:loc["end"]])
            if "gold_id" in entry and not (L.MIN_QUOTE_WORDS <= wc <= L.MAX_QUOTE_WORDS):
                problems.append(f"{slug}/{sid}: {entry['gold_id']}: {wc} words is outside {L.MIN_QUOTE_WORDS}..{L.MAX_QUOTE_WORDS}")
        (HERE / "transcripts" / slug).mkdir(parents=True, exist_ok=True)
        (HERE / "gold" / slug).mkdir(parents=True, exist_ok=True)
        (HERE / "transcripts" / slug / f"{sid}.json").write_text(
            json.dumps(record(slug, sid, text, upload, title, venue, kind, video), indent=1, ensure_ascii=False) + "\n")
        (HERE / "gold" / slug / f"{sid}.json").write_text(json.dumps(gold, indent=1, ensure_ascii=False) + "\n")
    (HERE / "roster.json").write_text(json.dumps({"roster": ROSTER}, indent=1) + "\n")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"wrote {len(FIXTURES)} transcripts; positives {sum(len(f[3]['positives']) for f in FIXTURES)}, "
          f"negatives {sum(len(f[3]['negatives']) for f in FIXTURES)}; every gold quote grounds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
