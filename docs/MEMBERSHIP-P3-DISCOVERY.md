# P3 discovery for the seven, and what the identity screen found first

Run 2026-09-18 from repo-0. 98 candidates, 14 per person, none below the
three-source floor. Nothing was fetched: caption fetching is still IP-blocked on
this machine, and discovery makes no caption requests.

## The existing 50 did not move

```
leaders        50 -> 57
total_sources  806 -> 904
every one of the original 50 blocks compares equal as sorted JSON
```

`--only` is what merges rather than replaces. `discover_sources.py` now also
refuses a run that would drop anyone the file already holds, so the flag is no
longer the only guard.

## Why it ran now, when it was parked this morning

The parking reason was wrong and worth recording as such. I said the machine's
YouTube IP block stopped discovery, without testing it. One `ytsearch` probe
returned results normally, and `caption_probe()` is defined in
`discover_sources.py` and never called, so discovery issues no caption requests.
The block is per-endpoint.

The REAL reason not to run it turned up while checking: leaders discovery had no
pacing at all, because commit `9925c0e` paced `discover_pundits.py` and left this
path at **eight unpaced workers**. That is the configuration `BACKLOG.md` blames
for 202 IP blocks in the pundits pilot. It is fixed, and this run used three
workers at 1.5s: 27 seconds for one person, 62 for the other six.

## The screen ran before anything was fetched

Extraction is the first stage that spends, so the screen goes in front of it.

```
98 candidates:  pass 66   review 32   reject 0
signal failures: identity 2, exclusivity 31, aboutness 0

  cathie-wood            pass 11  review  3  reject  0
  marc-andreessen        pass 10  review  4  reject  0
  chamath-palihapitiya   pass 10  review  4  reject  0
  david-sacks            pass  6  review  8  reject  0
  bill-gurley            pass  9  review  5  reject  0
  vinod-khosla           pass 12  review  2  reject  0
  tom-lee                pass  8  review  6  reject  0
```

### It earned its keep on the first run

**Three `tom-lee` candidates are a different Tom Lee.** The physician who founded
One Medical, not Fundstrat's Thomas J. Lee:

```
Keynote   Tom Lee, Founder & CEO, One Medical Group
FestiHealth | Tom Lee Keynote: Between Bricks & Clicks
Vator Splash Health Closing Fireside with Bambi Francisco and Tom Lee
```

That is the namesake class the plan flagged for exactly this slug, where
`name_in()` matches "s-lee-ping", caught before a single judge call. A fourth,
"Cryptocurrency Price Predictions with Thomas Lee", is the RIGHT person and was
flagged only because "Thomas" is not "Tom"; review is the safe direction for
that.

### What the 31 exclusivity flags are

Mostly genuine two-person recordings, which is what `review` means: Malcolm
Gladwell with Bill Gurley, Bill Gates with Vinod Khosla, Ezra Klein and Larry
Summers with David Sacks, Scott Kupor and Jeff Jordan under `marc-andreessen`.
Someone has to decide who is being transcribed before those are extracted.

A handful are title-case phrases the pattern reads as names: "First Principles",
"Silicon Valley", "Growth Stocks", "Must-Read Books". That is the residual noise
the screen's own test records, and it costs a human glance rather than a judge
call.

## What happens next

1. Rotate the VPN; `repo-3/data-pundits/logs/NEEDS_IP_ROTATION` is the flag to
   watch and repo-3's loop re-probes every 60 seconds.
2. Fetch into `data/transcripts_web/<slug>/`, **never** `data/transcripts/`.
3. Re-run the screen over the fetched transcripts, where `aboutness` gains its
   name-density signal and `own_voice` gains speaker labels if the captions carry
   them. On the leaders corpus 0 of 664 do.
4. Then extraction, which is where spending starts.
