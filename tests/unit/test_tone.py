"""The tone measurement (util/tone.py) that the measured `tone_hz` prop will rest on.

Synthetic signals pin what the method can and cannot tell apart; one file built by ffmpeg
proves the channels come out of the decoder in their own order, since a left and a right
swapped in deinterleaving would pass every single-tone file and fail only the one that
exists to catch a swap.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from loremfile.util import tone
from loremfile.util.ffmpeg import decode_pcm, run

RATE = 8000


def sine(frequency: float, amplitude: int = 12_000, seconds: float = 1.0) -> list[int]:
    return [
        round(amplitude * math.sin(2 * math.pi * frequency * i / RATE + 0.3))
        for i in range(int(RATE * seconds))
    ]


def test_a_tone_on_a_bin_measures_to_within_a_hundredth() -> None:
    for frequency in (440.0, 880.0, 1000.0, 3000.0):
        found = tone.dominant(sine(frequency), RATE)
        assert found is not None
        assert abs(found[0] - frequency) < 0.01, frequency
        assert found[1] > 0.999, frequency


def test_a_tone_between_bins_carries_the_bias_the_tolerance_allows_for() -> None:
    """At most 0.17 Hz: the least any tolerance on these measurements has to allow."""
    frequencies = [437.1 + 0.1 * step for step in range(10)] + [440.5, 879.5, 880.25]
    worst = max(abs(tone.dominant(sine(f), RATE)[0] - f) for f in frequencies)  # type: ignore[index]
    assert round(worst, 2) == 0.17


def test_each_channel_is_measured_on_its_own() -> None:
    assert tone.tone_hz([sine(440), sine(880)], RATE) == [440.0, 880.0]


def test_a_tone_under_noise_is_still_a_tone() -> None:
    noise = random.Random(2)
    noisy = [sample + noise.randint(-3000, 3000) for sample in sine(440)]
    assert tone.tone_hz([noisy], RATE) == [440.0]


def test_silence_noise_and_two_equal_tones_are_not_a_tone() -> None:
    noise = random.Random(1)
    hiss = [noise.randint(-8000, 8000) for _ in range(RATE)]
    chord = [a + b for a, b in zip(sine(440, 6000), sine(660, 6000), strict=True)]
    assert tone.tone_hz([[0] * RATE, hiss, chord], RATE) == [None, None, None]
    found = tone.dominant(chord, RATE)
    assert found is not None and round(found[1], 3) == 0.707, "two equal tones share the energy"


def test_too_little_audio_is_not_measured() -> None:
    assert tone.dominant(sine(440, seconds=0.05), RATE) is None


def test_the_decoder_keeps_left_and_right_in_their_places(tmp_path: Path) -> None:
    target = tmp_path / "left-440-right-880.wav"
    run(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000:duration=1.5",
            "-filter_complex",
            "[0:a][1:a]join=inputs=2:channel_layout=stereo[a]",
            "-map",
            "[a]",
            str(target),
        ]
    )
    pcm = decode_pcm(target, channels=2, start=tone.START_S, seconds=tone.SECONDS, rate=tone.RATE)
    assert [len(channel) for channel in pcm] == [tone.RATE, tone.RATE]
    assert tone.tone_hz(pcm, tone.RATE) == [440.0, 880.0]
