export const meta = {
  name: 'discover-leader-sources',
  description: 'Find and verify long-form public speaking appearances on YouTube for each leader, with caption availability confirmed',
  phases: [
    { title: 'Discover', detail: 'One agent per leader: search YouTube, verify the subject speaks at length, confirm captions exist' },
    { title: 'Audit', detail: 'Check each leader\'s slate for venue diversity, duplicate shows, and subject dominance' },
  ],
}

// args: { roster: [{slug,name,role,company,sector}], target_per_leader: 6, repo: "/abs/path" }
const ROSTER = args.roster
const TARGET = args.target_per_leader || 6
const REPO = args.repo

const SOURCE_SCHEMA = {
  type: 'object',
  properties: {
    leader_slug: { type: 'string' },
    aliases: {
      type: 'array',
      description: 'Extra strings that must be blinded for this leader: nicknames, the company\'s common acronym, alternate company names, and any SPELLING VARIANT you actually observed in the captions you checked (speech recognition mangles surnames constantly). Include only strings that identify this person or company.',
      items: { type: 'string' },
    },
    repairs: {
      type: 'array',
      description: 'Speech-recognition corruptions worth correcting before grading, as explicit find/replace pairs. Only include ones you SAW in the captions you actually inspected. Do not guess.',
      items: {
        type: 'object',
        properties: {
          wrong: { type: 'string', description: 'The corrupted string exactly as it appears in the captions' },
          right: { type: 'string', description: 'The correct term' },
        },
        required: ['wrong', 'right'],
      },
    },
    sources: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          source_id: { type: 'string', description: 'lowercase-hyphenated, unique within this leader, e.g. "dwarkesh-2024"' },
          video_id: { type: 'string', description: 'The 11-character YouTube video id, nothing else' },
          title: { type: 'string' },
          venue: { type: 'string', description: 'Channel or show name, e.g. "Dwarkesh Patel", "NVIDIA GTC"' },
          kind: { type: 'string', description: 'One of: podcast, interview, keynote, fireside, panel' },
          year: { type: 'integer' },
          duration_min: { type: 'integer' },
          captions_confirmed: { type: 'boolean', description: 'True only if you ran the caption check and it returned text' },
          subject_dominant: { type: 'boolean', description: 'True if the subject does a large share of the talking. False for panels where they are one of five.' },
          verification_note: { type: 'string', description: 'What you did to confirm this is the right person speaking at length, and what the caption check returned.' },
        },
        required: ['source_id', 'video_id', 'title', 'venue', 'kind', 'year', 'duration_min', 'captions_confirmed', 'subject_dominant', 'verification_note'],
      },
    },
    shortfall_reason: {
      type: 'string',
      description: 'If you returned fewer than the target number of sources, say exactly why: few appearances exist, captions disabled, non-English, or short-format only. Write "none" if you met the target.',
    },
  },
  required: ['leader_slug', 'aliases', 'repairs', 'sources', 'shortfall_reason'],
}

phase('Discover')
const found = await parallel(ROSTER.map(p => () => agent(
  `Find ${TARGET} verified long-form public speaking appearances by ${p.name} (${p.role}, ${p.company}) on YouTube.

These transcripts will be used to judge how this person thinks, so the quality of what you pick decides the quality of the whole study. A wrong video silently corrupts a leader's score.

## Tools you must use

Search YouTube with yt-dlp:
    yt-dlp --flat-playlist --print "%(id)s | %(duration)s | %(channel)s | %(title)s" "ytsearch20:<query>"

Confirm captions actually exist and are English, for EVERY video you propose:
    cd ${REPO} && .venv/bin/python -c "
from youtube_transcript_api import YouTubeTranscriptApi
api=YouTubeTranscriptApi(); l=api.list('VIDEO_ID')
t=l.find_generated_transcript(['en'])
d=t.fetch(); print(len(d),'cues |',' '.join(x.text for x in d[:40]))"

Run several different searches. Vary them: the person's name plus "interview", plus "podcast", plus "keynote", plus "fireside", plus the names of specific shows, plus the company's conference name.

## What to select

Aim for ${TARGET} sources with a MIX of formats and venues, because format changes what a transcript can show. A keynote reveals how someone structures an argument; a hard interview reveals how they handle a changed premise. Ideally include at least one keynote or prepared talk and at least two long-form interviews or podcasts.

Requirements for every source:
- The subject genuinely speaks at length. Reject videos ABOUT the person, news packages, clip compilations, and fan edits.
- 20 minutes or longer. Prefer 40 minutes and up. If almost nothing long exists for this person, take the longest available and say so in shortfall_reason.
- English. Reject non-English audio.
- English captions confirmed by actually running the check above. Set captions_confirmed true only when the command printed real text.
- No more than 2 sources from the same channel or show, so one interviewer's style does not dominate the leader's profile.
- Spread across years where possible.

## Also return

- 'aliases': strings that must be hidden when the transcript is blinded. Include the company's spoken acronym, alternate company names, and any misspelling of the surname you SAW in the caption samples you printed. This matters: captions rendered "Kurian" as "Curran" and "Kurion" in one real case.
- 'repairs': speech-recognition corruptions of product or technical terms you actually observed, as find/replace pairs. Only what you saw. Do not invent plausible ones.

Read the first 40 caption cues of each video you propose. That is how you confirm the right person is speaking and how you spot the misspellings. Return raw structured data.`,
  { label: `find:${p.slug}`, phase: 'Discover', schema: SOURCE_SCHEMA }
)))

const ok = found.filter(Boolean)
const totalSources = ok.reduce((n, r) => n + (r.sources || []).length, 0)
log(`Discovered ${totalSources} candidate sources across ${ok.length}/${ROSTER.length} leaders`)
const thin = ok.filter(r => (r.sources || []).length < TARGET)
if (thin.length) log(`${thin.length} leaders came in under the target of ${TARGET}: ${thin.map(r => `${r.leader_slug}(${r.sources.length})`).join(', ')}`)

phase('Audit')
const AUDIT_SCHEMA = {
  type: 'object',
  properties: {
    leader_slug: { type: 'string' },
    drop_source_ids: { type: 'array', description: 'source_ids that should NOT be used, with the reason given in issues.', items: { type: 'string' } },
    issues: { type: 'array', items: { type: 'string' } },
    diversity_verdict: { type: 'string', description: 'Does this slate span formats and venues, or is it monotonous? Be specific.' },
    ok: { type: 'boolean' },
  },
  required: ['leader_slug', 'drop_source_ids', 'issues', 'diversity_verdict', 'ok'],
}

const audited = await parallel(ok.map(r => () => agent(
  `Audit this slate of proposed speaking sources for one leader before it is used in a scoring study.

${JSON.stringify(r)}

Check, and use yt-dlp or the caption check to verify anything you doubt:
1. Is every video_id a real 11-character YouTube id, and does it actually exist? Check with:
   yt-dlp --skip-download --print "%(id)s | %(duration)s | %(channel)s | %(title)s" "https://www.youtube.com/watch?v=<id>"
2. Does the subject actually speak at length in each, rather than being discussed by others?
3. Is any video a duplicate of another in the slate, a re-upload, or a clip taken from a longer one already listed?
4. Are more than 2 sources from the same channel?
5. Is the slate monotonous, for example six short television hits with no long-form conversation? Say so.
6. Does any entry claim captions_confirmed true that you cannot verify?

List the source_ids to drop and say why. If the slate is sound, return ok true with an empty drop list. Do not manufacture problems.`,
  { label: `audit:${r.leader_slug}`, phase: 'Audit', schema: AUDIT_SCHEMA }
)))

const auditBySlug = Object.fromEntries(audited.filter(Boolean).map(a => [a.leader_slug, a]))
const final = ok.map(r => {
  const a = auditBySlug[r.leader_slug]
  const drop = new Set(a ? a.drop_source_ids : [])
  return {
    ...r,
    sources: (r.sources || []).filter(s => !drop.has(s.source_id)),
    dropped: (r.sources || []).filter(s => drop.has(s.source_id)).map(s => s.source_id),
    audit: a || null,
  }
})

const kept = final.reduce((n, r) => n + r.sources.length, 0)
log(`After audit: ${kept} sources kept, ${totalSources - kept} dropped`)
return { leaders: final, total_sources: kept, dropped: totalSources - kept }
