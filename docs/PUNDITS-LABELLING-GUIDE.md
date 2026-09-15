# Pundits labelling guide (P6 speaker checks, P7 labels and probe audits)

This guide is for the people who label recordings for the pundits study. Labels
decide which recordings are graded and whether the judges' attribution can be
trusted, so a label is a measurement, and these rules keep it one.

The label files live only in the private data repository, under
`data-pundits/labels/` and `data-pundits/logs/pilot/`. Nothing here contains a
lean label, and nothing a model wrote may be recorded as a human label.

## Rules for every label

1. **A human decides every label.** `checked_by` names the person, never a
   model. A model may draft a pre-label only if the plan decision on
   pre-labels allows it (open decision 2 in `docs/PUNDITS-PLAN.md`). A draft is
   stored with `drafted_by_model: true`, and the person who confirms or changes
   it is the one recorded in `checked_by`. The report says how many labels
   began as drafts, because a draft can anchor the person reading it.
2. **Two people label independently** for P7 attribution windows and the quote
   audit. Neither sees the other's labels. If they disagree past the tolerance
   stated in each section, a third person adjudicates, and all three labels are
   kept.
3. **Listen, do not only read.** Automatic captions have no speaker labels.
   Each checklist row carries the video URL. Use the audio to decide who speaks.
4. **Unsure is a valid answer.** Use `notes` to say why. Never guess to fill a
   field. A blank field keeps the P6 gate INCONCLUSIVE, which is correct.

## P6: speaker verification of pilot recordings

File to fill: `data-pundits/logs/pilot/human_checklist.json`. Copy each
completed row into `data-pundits/logs/pilot/human_labels.json`, keyed the same.
`scripts/pundits_pilot.py report` reads only the labels file.

| Field | Values | Meaning |
|---|---|---|
| `subject_present` | true / false | The roster person speaks in the recording. False means a wrong-person record, and it is counted and reported. |
| `main_speaker` | true / false | The person speaks the most words of any single speaker, OR at least 35% of all words. A host who mostly listens to a guest is not the main speaker. |
| `venue` | one of the venues below | The format of THIS recording, whoever uploaded it. |
| `checked_by` | a person's name or initials | Who listened. |
| `notes` | free text | Anything unusual: a substitute host for part of the show, a clip compilation, a re-upload of an older recording. |

Automatic pre-checks have already failed recordings with no upload date, an
upload outside the window, an upload after an archival subject's last
recording, or a substitute host named in the opening. The `hints` field shows
what the pre-check noticed, for example that the subject is never named.

### Venues

Decide by counting the other live voices in the conversation, not by who hosts
or which channel or network airs it. Played clips are not live voices. If a
recording mixes formats, record the format that fills most of it. The judges'
rubric carries these exact definitions, so your labels and theirs can be compared.

| Venue | Definition |
|---|---|
| `own_show_monologue` | The subject speaks to the audience on their own show, with no other live voice. |
| `reaction_stream` | The subject plays other material and comments on it, with no other live voice. |
| `debate` | An organised exchange with at least one named opponent, usually with a moderator or turns. |
| `guest_interview` | Exactly one other live voice: an interviewer who runs the conversation and questions the subject. |
| `hosted_interview` | The subject runs the conversation and questions exactly one guest. |
| `panel_show` | Two or more other live voices trade views with the subject, whoever hosts: a split-screen panel, a roundtable, a co-hosted show. |
| `tv_segment` | An anchor-led broadcast news segment, one-on-one or pre-packaged, that is not a multi-guest panel. |
| `speech_or_lecture` | A prepared talk to a live audience, with or without questions afterwards. |
| `other` | None of these. |

Examples: Ana Kasparian with three other guests on a Piers Morgan split screen,
or on Bill Maher's Overtime, is `panel_show`. Piers Morgan interviewing her alone
is `guest_interview`. A regular Young Turks episode she co-hosts with Cenk Uygur
is `panel_show`. For `other`, say what it is in `notes`, for example "gaming".

## P7: attribution windows (30 windows, 6 per format)

Each window is 10 minutes of one recording, cut by
`scripts/pundits_label_kit.py windows` into its own file. The judges receive
exactly the same text. Label word spans:

- `subject`: the roster person speaks.
- `interlocutor`: anyone else live in the recording: host, guest, caller,
  co-host.
- `clip`: played material, including the subject's own older clips.

Record spans as word-index ranges over the window's `words` list, with
start inclusive and end exclusive. Every word gets exactly one label. The tool
reports each person's subject share. If two people's subject shares differ by
more than 5 points, a third person adjudicates that window. Agreement is
reported as Krippendorff's alpha over word labels before any judge output is
compared.

## P7: quote attribution audit (300 quotes)

`scripts/pundits_label_kit.py quotes` draws 60 evidence quotes per venue from
pilot grades, balanced by judge and mode. The judge's own speaker label is
hidden from the person labelling. For each quote:

- find it in the audio with the timestamp hint;
- record `spoken_by_subject` as `yes`, `no` or `not_found`, where `not_found`
  means the words are not in the recording, which is itself a finding;
- use `notes` for partial matches.

## P7: mirror pairs and intervention probes

These texts are edited versions of real transcripts. A model may draft them,
and every draft carries `drafted_by_model: true` and `audit_status: pending`.
A person audits each one before use:

- **Mirror pairs:** the swapped version keeps the structure, hedging, and
  charity of the original, and the swap does not change historical truth or
  plausibility. If it would, use a synthetic symmetric scenario instead.
- **Intervention probes:** the inserted span is 150-300 words, reads as the
  same speaker, and does only what its label says. A strawman edit misstates
  an opposing view that is present in the transcript. An overclaim edit states
  more confidence than the support shown. A sham edit makes neutral wording
  changes of matched length. A beneficial edit adds an accurate steel-man.

**Held-out probes stay sealed.** Held-out files are not opened by anyone tuning
the rubric or prompt until the rubric is frozen. Any rubric change after a
held-out run voids those runs.

## Time estimate

From the plan: 30 windows at about 40 minutes each is 20 hours per person, 300
quotes at about 1 minute each is 5 hours per person, and probe audits add about
3 hours. With two labellers and adjudication that is about 55 hours. The P6
pilot checklist adds about 2 minutes per recording to skim audio for presence
and main speaker, about 8 hours for 240 recordings.
