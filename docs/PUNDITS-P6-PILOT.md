# P6 discovery pilot (interim, 2026-09-14)

**Gate P6: INCONCLUSIVE.** No human speaker label exists yet, and the plan
requires a person to check every selected pilot recording before grading. The
fetch also stopped at 22 of 240 recordings after YouTube throttled it. A slower
retry is scheduled. This document is updated when it finishes.

Records are in the private data repository (commit `1a55da7`):
`sources/pilot_discovered.json`, `sources/pilot_manifest.jsonl`,
`logs/pilot/precheck.json`, `logs/pilot/human_checklist.json`,
`logs/pilot/fetch_errors.jsonl`.

## Roster used

39 people: 13 left, 13 right, 13 heterodox. Each label comes from cited outside
sources, which are held privately. All 18 operator-named people are on it. Two
people have no verified YouTube channel: Glenn Greenwald, whose show is on
Rumble, and John McWhorter.

Balance was reached by choosing who is on the roster, not by choosing labels.
The first draft of 40 came out 14 left, 20 right and 6 heterodox by its sources.
The right-labelled and left-labelled additions were replaced with researched
candidates whose sources call them centrist or heterodox.

## Pilot people

Left: Steven Bonnell (Destiny), Ezra Klein, Sam Seder, Hasan Piker. Right:
Asmongold, Charlie Kirk (archival), Ben Shapiro, Matt Walsh. Heterodox: Coleman
Hughes, Ana Kasparian. All ten are operator-named.

## Discovery

`scripts/discover_pundits.py`, listing depth 1500 per channel tab.

```
person            attempted  accepted  own_channel  debate  interlocutor
ezra-klein              369       288          285       0             3
coleman-hughes          587       245          244       0             1
ben-shapiro            1617       526          523       1             2
steven-bonnell         1629      1229         1229       0             0
charlie-kirk           1627       140          127       9             4
ana-kasparian          3099      1323         1320       0             3
sam-seder              3048      1568         1566       0             2
asmongold              1846       618          618       0             0
hasan-piker            1629       419          419       0             0
matt-walsh             1565       512          512       0             0
total                 17016      6868         6843      10            15
```

Own channels supply almost everything. Recordings on other channels are nearly
absent, because a title there must carry the full name or a handle AND a second
identity token. That matters for the plan's rule of at least 4 recordings with
an interlocutor per person. Own-channel uploads can still have an interlocutor,
such as Ezra Klein's interviews, and the human venue label decides.

### What the strict rule loses, measured

Per person, the rejected titles that had the name or handle but no second token,
and how many of those name another roster person:

```
person           no second token   names another roster person
ana-kasparian                 24     7
asmongold                     22     1
ben-shapiro                   22     7
charlie-kirk                  28     4
coleman-hughes                28     1
ezra-klein                    20     7
hasan-piker                   43     5
matt-walsh                     6     1
sam-seder                      7     2
steven-bonnell                70     5
```

Admitting "names another roster person" as the second token would let in
wrong-person and about-the-person titles. Examples from this list:
"Ezra Klein DESTROYS Sam Seder", a clip-style title, and "Candace Owens
Discusses The Charlie Kirk Investigation", which is about Kirk and not by him.
So the rule was left strict.

It does lose real guest appearances. Examples: "Joe Rogan Experience #2204 -
Matt Walsh", "Charlie Kirk | Club Random with Bill Maher", and "Ben Shapiro
Admits His Biggest Blind Spot | PBD Podcast #842". In each, the second token
that would prove it is the HOST's show name, which is not on the guest's roster
entry.

**Decision for the operator.** There are three options.

- **(a) Keep the rule strict.** Cost: few recordings with an interlocutor, so
  the plan's minimum of 4 may fail for reaction-stream people.
- **(b) Treat a roster person's own show name as a second token when that person
  hosts the channel.** For example, "Club Random" on Bill Maher's channel would
  prove a guest appearance. Cost: one more rule to test, and it only helps
  guests of roster hosts.
- **(c) Keep a separate list of known interview shows as venue tokens.** Cost:
  a hand-kept list, which is a selection choice that has to be reviewed.

Recommendation: (b), because it uses channel ids the roster already verified,
so it cannot admit a namesake.

## Sample and fetch

A seeded draw of 24 candidates per person (seed 20260914). Other-channel
candidates take up to half of the draw, because they are scarce. The draw is
216 own-channel, 9 debate and 15 interlocutor.

```
attempted 240   succeeded 22   failed 218
error_taxonomy: ip_blocked_or_ratelimited 202, video_unavailable 16
```

The circuit breaker opened after 4 consecutive throttles. No other fetcher was
running on this machine, so the throttle came from this run's own traffic: 17,016
listing entries during discovery, then caption and metadata requests. All 16
unavailable videos are Ana Kasparian's. They are probably members-only TYT uploads,
which bears on her supply.

Retry: 45 minutes of cool-down, then 2 workers at 8 to 60 seconds between
requests, written to `logs/pilot/fetch_errors_retry1.jsonl`.

## Automatic pre-check on the 22 fetched records

```
NEEDS_HUMAN 21   FAIL 1 (uploaded 20191028, outside the window 20210913-20260913)
```

A FAIL is only what the record proves: no upload date, outside the window, after
an archival subject's last recording, or a substitute host in the opening. Every
other recording waits for a person.

## What the operator needs to do

1. Fill `data-pundits/logs/pilot/human_checklist.json` with the rules in
   `docs/PUNDITS-LABELLING-GUIDE.md`, then copy the rows into
   `logs/pilot/human_labels.json`.
2. Choose (a), (b) or (c) above.
3. Then run:
   `.venv/bin/python scripts/pundits_pilot.py report --study pundits --manifest data-pundits/sources/pilot_manifest.jsonl --precheck data-pundits/logs/pilot/precheck.json --human data-pundits/logs/pilot/human_labels.json --roster data-pundits/roster/final.json --out data-pundits/logs/pilot/report.json`.

   It returns PASS, FAIL or INCONCLUSIVE, with per-person yield, a 95% interval,
   the one-sided 80% lower bound, and the candidate count the full run needs.
