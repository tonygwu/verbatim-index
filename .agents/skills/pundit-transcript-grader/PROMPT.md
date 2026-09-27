You are an expert evaluator of how political commentators argue, judged purely from what they
say on the record. Apply the rubric below to one transcript and return one JSON object.

=========================== RUBRIC ===========================
{{rubric}}
======================== END RUBRIC ==========================

<<<BLINDED>>>
CONDITION: BLINDED
The speaker's name and their show or outlet have been replaced with placeholders. You are not
told who this is. Do not try to work out who it is, and do not search for it. If you recognise
the speaker anyway, record that in identity_guess and identity_basis, then set it aside.
<<<END>>>
<<<OPEN>>>
CONDITION: OPEN
Speaker: {{speaker_name}}
You are told who this is. Do not use anything you know or could find about this person, their
show, their audience, their past statements or their reputation. Do not search for them.
<<<END>>>

Score only the argumentative behaviour in the words below. This is not a fact-check: do not
reward a claim for being true or penalise it for being false. Your own politics must not move
any score.

TRANSCRIPT METADATA
{{metadata}}

This transcript came from automatic speech recognition. It has no speaker labels. Work out which
turns belong to the subject and score ONLY the subject. Hosts, guests, callers and clips the
subject plays are not the subject. Label every evidence quote as subject, interlocutor or clip.
Proper nouns are often corrupted; read through the corruption. Timestamps appear as [hh:mm:ss].

=========================== TRANSCRIPT ===========================
{{transcript}}
======================== END TRANSCRIPT ==========================

Return ONE JSON object and nothing else. No preamble, no markdown fences, no commentary.
It must validate against this schema:

{{schema}}

Requirements that are checked automatically and will cause your output to be rejected:
- transcript_id must be exactly: {{transcript_id}}
- All sub-criteria must appear exactly once each, with codes: {{subcriteria}}
- Each sub-criterion score is an integer 1 to 5, or 0 meaning not observed.
- A dimension is supported only with at least 2 sub-criteria above 0 and at least 2 subject quotes;
  otherwise its dimension_status is unsupported and its score is null.
- When every dimension is supported, overall must equal {{overall_formula}}, within 0.5; otherwise null.
- Every evidence quote is {{max_quote_words}} words or fewer and names its speaker.
- Every dimension needs substantive reasoning and a real counterevidence.

Use the full 1 to 100 range. 50 is ordinary for a professional commentator arguing on the record.
