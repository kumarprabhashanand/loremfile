"""Text corpora: Latin lorem ipsum, per-script pseudo-text, and emoji (docs/05 §7).

No third-party sentences are copied. The Latin passage is the public-domain lorem ipsum
extended by a derived vocabulary; every other script is generated from a fixed character
inventory in ``data/scripts/``, so the output is ours and reproducible.

Pseudo-text is not meaningful language and does not claim to be. It exists so that
encoding, shaping and line-breaking can be tested with realistic byte patterns.
"""

from __future__ import annotations

import functools
import random
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
SCRIPTS = DATA / "scripts"

#: The canonical opening. Public domain.
LOREM_OPENING = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua."
)

#: Vocabulary the paragraphs are built from, derived from the standard passage.
LOREM_WORDS = [
    "lorem",
    "ipsum",
    "dolor",
    "sit",
    "amet",
    "consectetur",
    "adipiscing",
    "elit",
    "sed",
    "do",
    "eiusmod",
    "tempor",
    "incididunt",
    "ut",
    "labore",
    "et",
    "dolore",
    "magna",
    "aliqua",
    "enim",
    "ad",
    "minim",
    "veniam",
    "quis",
    "nostrud",
    "exercitation",
    "ullamco",
    "laboris",
    "nisi",
    "aliquip",
    "ex",
    "ea",
    "commodo",
    "consequat",
    "duis",
    "aute",
    "irure",
    "in",
    "reprehenderit",
    "voluptate",
    "velit",
    "esse",
    "cillum",
    "eu",
    "fugiat",
    "nulla",
    "pariatur",
    "excepteur",
    "sint",
    "occaecat",
    "cupidatat",
    "non",
    "proident",
    "sunt",
    "culpa",
    "qui",
    "officia",
    "deserunt",
    "mollit",
    "anim",
    "id",
    "est",
    "laborum",
    "accusantium",
    "doloremque",
    "laudantium",
    "totam",
    "rem",
    "aperiam",
    "eaque",
    "ipsa",
    "quae",
    "ab",
    "illo",
    "inventore",
    "veritatis",
    "quasi",
    "architecto",
    "beatae",
    "vitae",
    "dicta",
    "explicabo",
    "nemo",
    "voluptatem",
    "quia",
    "voluptas",
    "aspernatur",
    "aut",
    "odit",
    "fugit",
    "sequi",
    "nesciunt",
    "neque",
    "porro",
    "quisquam",
    "dolorem",
    "adipisci",
    "numquam",
    "eius",
    "modi",
    "tempora",
    "incidunt",
    "magnam",
    "quaerat",
    "ratione",
    "sequitur",
    "alias",
    "perferendis",
    "doloribus",
    "asperiores",
    "repellat",
    "temporibus",
    "autem",
    "quibusdam",
    "officiis",
    "debitis",
    "rerum",
    "necessitatibus",
    "saepe",
    "eveniet",
    "voluptates",
    "repudiandae",
    "molestiae",
    "recusandae",
    "itaque",
    "earum",
    "hic",
    "tenetur",
    "sapiente",
    "delectus",
    "reiciendis",
    "maiores",
    "placeat",
    "facere",
    "possimus",
    "omnis",
    "assumenda",
    "repellendus",
    "similique",
    "culpa",
    "dolorum",
    "fuga",
]

#: Scripts with a character inventory in data/scripts/.
SCRIPT_NAMES = (
    "greek",
    "cyrillic",
    "armenian",
    "georgian",
    "hebrew",
    "arabic",
    "devanagari",
    "bengali",
    "tamil",
    "thai",
    "hiragana",
    "katakana",
    "kanji",
    "hanzi",
    "hangul_jamo",
)

#: Scripts written right to left. Callers that care about direction check this.
RTL_SCRIPTS = frozenset({"hebrew", "arabic"})

#: Scripts written without spaces between words.
UNSPACED_SCRIPTS = frozenset({"thai", "kanji", "hanzi", "hiragana", "katakana"})


@functools.cache
def inventory(script: str) -> tuple[str, ...]:
    """The character inventory for a script, cached after the first read."""
    if script not in SCRIPT_NAMES:
        raise KeyError(f"unknown script '{script}'; known: {', '.join(SCRIPT_NAMES)}")
    path = SCRIPTS / f"{script}.txt"
    return tuple(path.read_text(encoding="utf-8").split())


@functools.lru_cache(maxsize=1)
def emoji_sequences() -> tuple[str, ...]:
    """The fixed emoji list: singletons, keycaps, flags, skin tones, ZWJ families."""
    return tuple(DATA.joinpath("emoji.txt").read_text(encoding="utf-8").split("\n")[:-1])


def words(rng: random.Random, count: int) -> list[str]:
    """``count`` lorem words drawn with the caller's seeded RNG."""
    return [rng.choice(LOREM_WORDS) for _ in range(count)]


def sentence(rng: random.Random, min_words: int = 6, max_words: int = 18) -> str:
    """One capitalised, full-stopped lorem sentence."""
    body = words(rng, rng.randint(min_words, max_words))
    return body[0].capitalize() + " " + " ".join(body[1:]) + "."


def paragraph(rng: random.Random, min_sentences: int = 3, max_sentences: int = 7) -> str:
    return " ".join(sentence(rng) for _ in range(rng.randint(min_sentences, max_sentences)))


def text(rng: random.Random, paragraphs: int, *, opening: bool = True) -> str:
    """``paragraphs`` paragraphs, separated by blank lines.

    With ``opening`` the first paragraph starts with the canonical passage, which is what
    makes a lorem fixture recognisable at a glance.
    """
    blocks = [paragraph(rng) for _ in range(paragraphs)]
    if opening and blocks:
        blocks[0] = f"{LOREM_OPENING} {blocks[0]}"
    return "\n\n".join(blocks)


def pseudo_word(rng: random.Random, script: str, min_len: int = 2, max_len: int = 8) -> str:
    """One pseudo-word in the given script.

    Korean composes real Hangul syllables from jamo rather than emitting bare jamo,
    because bare jamo do not render as text anyone would recognise.
    """
    if script == "hangul_jamo":
        return "".join(_hangul_syllable(rng) for _ in range(rng.randint(1, 3)))
    chars = inventory(script)
    return "".join(rng.choice(chars) for _ in range(rng.randint(min_len, max_len)))


def _hangul_syllable(rng: random.Random) -> str:
    """Compose one precomposed Hangul syllable (U+AC00 block)."""
    lead = rng.randrange(19)
    vowel = rng.randrange(21)
    tail = rng.randrange(28)  # 0 means no final consonant
    return chr(0xAC00 + (lead * 21 + vowel) * 28 + tail)


def pseudo_text(rng: random.Random, script: str, word_count: int) -> str:
    """A run of pseudo-text in one script.

    Unspaced scripts are joined without spaces, which is what makes them useful for
    testing line breaking; everything else is space separated.
    """
    parts = [pseudo_word(rng, script) for _ in range(word_count)]
    return ("" if script in UNSPACED_SCRIPTS else " ").join(parts)


def emoji_run(rng: random.Random, count: int) -> str:
    """A space-separated run of emoji sequences drawn from the fixed list."""
    sequences = emoji_sequences()
    return " ".join(rng.choice(sequences) for _ in range(count))
