#!/usr/bin/env python3
"""Quota-free regression: which phrases gate G3 `committed` accepts and refuses.

Added 2026-09-15 with the decision to read "on track to" as committed.

WHY THIS FILE EXISTS. The G3 pass list is prose inside a model-facing spec, and
prose drifts. Before this change the verifier threw away every dated corporate
commitment phrased "we are on track to ship X by June", which is the single most
common way a public-company CEO states a dated deliverable. Six measured leads
across Mary Barra, Peter Beck and Cristiano Amon died on that wording alone.

The opposite error is the expensive one, so it is pinned here too. "We want to"
states a preference and must keep failing. Gwynne Shotwell's "we want to land it
on the moon before 2022" is the case that made the distinction concrete: it
sounds exactly as confident as a commitment and asserts nothing about what will
happen. If a later edit ever collapses the two, this test fails.

These assertions are on the SHARED policy text, so they hold for the extractor
and the verifier at once. ELIGIBILITY.md reaches both through the
{{ELIGIBILITY_POLICY}} marker and is hashed into both contract ids.
"""
import re
import unittest

import predictions_lib as L

# The section that states the gate, isolated so a phrase appearing elsewhere in
# the document cannot satisfy an assertion by accident.
G3_START = "**G3 `committed`.**"
G3_END = "**G4 `own_voice`.**"

ACCEPTED = [
    "will", "is going to", "I expect", "I think X will", "I believe",
    "probably", "likely", "I'd bet",
    "on track to",   # added 2026-09-15
    "on track for",  # the preposition variant; Peter Beck uses it
]

REFUSED = [
    "Might", "could", "may", "maybe", "possibly",
    "we want to",      # preference, not expectation
    "I'd like to see",
    "hopeful",
]


def g3_section() -> str:
    text = L.read_spec(L.SKILL / L.VERIFICATION_SPEC)
    start = text.index(G3_START)
    return text[start:text.index(G3_END, start)]


class G3PhraseTests(unittest.TestCase):
    def setUp(self):
        self.section = g3_section()
        # The two phrase LISTS live in the first paragraph. The paragraphs after
        # it are explanatory prose that names "on track" while explaining it, so
        # scoping to paragraph one keeps prose from being read as a list entry.
        self.lists = self.section.split("\n\n")[0]
        self.prose = self.section[len(self.lists):]
        # The delimiter stays with the refusing half, because "Might" is itself
        # a refused word.
        cut = self.lists.index('"Might"')
        self.accept_half, self.refuse_half = self.lists[:cut], self.lists[cut:]

    def test_policy_reaches_the_verification_spec(self):
        """A phrase list nobody reads is not a policy."""
        self.assertIn(G3_START, L.read_spec(L.SKILL / L.VERIFICATION_SPEC))
        self.assertIn(G3_START, L.read_spec(L.SKILL / L.EXTRACTION_SPEC))

    def test_accepted_phrases_are_listed_on_the_accepting_side(self):
        for phrase in ACCEPTED:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.accept_half,
                              f"{phrase!r} must be on the G3 pass list")

    def test_refused_phrases_are_listed_on_the_refusing_side(self):
        for phrase in REFUSED:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.refuse_half,
                              f"{phrase!r} must be on the G3 fail list")

    def test_on_track_never_appears_on_the_refusing_side(self):
        """The regression this file was written for."""
        self.assertNotIn("on track", self.refuse_half)
        self.assertIn("on track to", self.accept_half)

    def test_want_to_never_appears_on_the_accepting_side(self):
        """Aspiration must not be readable as commitment.

        Shotwell 2019: "we want to land it on the moon before 2022".
        """
        self.assertNotIn("we want to", self.accept_half)

    def test_on_track_requires_a_dated_outcome(self):
        """A bare "we are on track" is a present condition, not a forecast."""
        self.assertRegex(
            self.section,
            re.compile(r"bare .we are on track.*?fails G1", re.DOTALL),
            "the spec must say a bare 'on track' fails, or the gate leaks",
        )

    def test_the_preference_versus_expectation_rule_is_stated(self):
        """The reason, not just the word list, so a model can generalise."""
        flat0 = " ".join(self.section.split())
        self.assertIn("asserts a present expectation about a future state", flat0)
        flat = " ".join(self.section.split())
        self.assertIn("asserts only a preference", flat)

    def test_policy_release_pins_the_current_text(self):
        """Editing the gate without re-pinning must fail loudly, not silently."""
        release = L.load_policy_release()
        self.assertEqual(
            release["contracts"],
            {"extract": L.extraction_contract()["contract_id"],
             "verify": L.verification_contract()["contract_id"]},
        )
        self.assertTrue(re.fullmatch(r"predictions-\d+\.\d+", release["release"]),
                        f"unexpected release name {release['release']!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
