"""M1.7: text corpora — Latin lorem, per-script pseudo-text, emoji (docs/05 §7)."""

from __future__ import annotations

import random

import pytest

from loremfile.util import lorem


def rng(seed: int = 1) -> random.Random:
    return random.Random(seed)


def test_text_starts_with_the_canonical_passage() -> None:
    assert lorem.text(rng(), 2).startswith(lorem.LOREM_OPENING)


def test_opening_can_be_suppressed() -> None:
    assert not lorem.text(rng(), 2, opening=False).startswith(lorem.LOREM_OPENING)


def test_paragraph_count_is_respected() -> None:
    assert len(lorem.text(rng(), 4).split("\n\n")) == 4


def test_text_is_reproducible_for_a_given_rng_seed() -> None:
    assert lorem.text(rng(7), 3) == lorem.text(rng(7), 3)


def test_different_seeds_give_different_text() -> None:
    assert lorem.text(rng(1), 3, opening=False) != lorem.text(rng(2), 3, opening=False)


def test_sentences_are_capitalised_and_terminated() -> None:
    text = lorem.sentence(rng())
    assert text[0].isupper()
    assert text.endswith(".")


def test_words_returns_the_requested_count() -> None:
    assert len(lorem.words(rng(), 25)) == 25


# --- per-script pseudo-text ------------------------------------------------


@pytest.mark.parametrize("script", lorem.SCRIPT_NAMES)
def test_every_script_has_a_usable_inventory(script: str) -> None:
    chars = lorem.inventory(script)
    assert chars, script
    assert all(len(c) == 1 for c in chars)
    assert len(chars) == len(set(chars))


@pytest.mark.parametrize("script", lorem.SCRIPT_NAMES)
def test_pseudo_text_is_reproducible(script: str) -> None:
    assert lorem.pseudo_text(rng(3), script, 8) == lorem.pseudo_text(rng(3), script, 8)


@pytest.mark.parametrize("script", lorem.SCRIPT_NAMES)
def test_pseudo_text_is_non_empty(script: str) -> None:
    assert lorem.pseudo_text(rng(), script, 5).strip()


def test_unknown_script_is_rejected() -> None:
    with pytest.raises(KeyError, match="unknown script"):
        lorem.inventory("klingon")


def test_unspaced_scripts_have_no_spaces() -> None:
    for script in lorem.UNSPACED_SCRIPTS:
        assert " " not in lorem.pseudo_text(rng(), script, 6)


def test_spaced_scripts_have_spaces() -> None:
    assert " " in lorem.pseudo_text(rng(), "greek", 6)


def test_hangul_composes_real_syllables_not_bare_jamo() -> None:
    text = lorem.pseudo_text(rng(), "hangul_jamo", 5)
    assert all(0xAC00 <= ord(c) <= 0xD7A3 for c in text if c != " ")


def test_kanji_inventory_encodes_in_shift_jis() -> None:
    """The shift-jis fixture can only use characters the charset can represent."""
    "".join(lorem.inventory("kanji")).encode("shift_jis")


def test_hanzi_inventory_encodes_in_gb2312() -> None:
    "".join(lorem.inventory("hanzi")).encode("gb2312")


def test_generated_hanzi_text_encodes_in_gb2312() -> None:
    lorem.pseudo_text(rng(), "hanzi", 200).encode("gb2312")


def test_generated_kanji_text_encodes_in_shift_jis() -> None:
    lorem.pseudo_text(rng(), "kanji", 200).encode("shift_jis")


def test_rtl_scripts_are_declared() -> None:
    assert {"hebrew", "arabic"} == lorem.RTL_SCRIPTS
    assert set(lorem.SCRIPT_NAMES) >= lorem.RTL_SCRIPTS


# --- emoji -----------------------------------------------------------------


def test_emoji_list_covers_the_documented_categories() -> None:
    sequences = lorem.emoji_sequences()
    assert sequences
    assert any("⃣" in s for s in sequences), "keycaps"
    assert any("\U0001f1e6" <= s[0] <= "\U0001f1ff" for s in sequences), "flags"
    assert any("\U0001f3fb" <= c <= "\U0001f3ff" for s in sequences for c in s), "skin tones"
    assert any("‍" in s for s in sequences), "ZWJ sequences"


def test_emoji_sequences_are_unique_and_non_empty() -> None:
    sequences = lorem.emoji_sequences()
    assert all(sequences)
    assert len(sequences) == len(set(sequences))


def test_emoji_run_is_reproducible() -> None:
    assert lorem.emoji_run(rng(5), 6) == lorem.emoji_run(rng(5), 6)


def test_emoji_survive_a_utf8_round_trip() -> None:
    run = lorem.emoji_run(rng(), 20)
    assert run.encode("utf-8").decode("utf-8") == run
