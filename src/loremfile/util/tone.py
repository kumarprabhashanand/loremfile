"""The frequency of a tone, measured per channel from decoded PCM.

The sine fixtures' descriptions name a frequency, 440 Hz and in one file 880 Hz on the right,
and a published number has to rest on the bytes. Goertzel rather than an FFT: it needs no
library the toolchain lacks, and a tone needs only a few hundred frequencies examined.

A coarse scan over a tenth of a second finds the peak to within the step, a scan of the
whole window at 1 Hz finds its bin, and a parabola through the log power of that bin and
its neighbours places it between them. A channel answers only when one frequency holds
nearly all of its energy: silence, noise or two tones of equal strength answer None.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: What to decode for a measurement: one second of the first audio stream, a quarter of a
#: second in so an encoder's start-up is not measured, at 8 kHz: tones up to 3.9 kHz.
START_S = 0.25
SECONDS = 1.0
RATE = 8000
#: The lowest frequency examined, and the coarse scan's window and step.
MIN_HZ = 20.0
COARSE_SECONDS = 0.1
COARSE_STEP_HZ = 5.0
#: Either side of the coarse peak, in 1 Hz steps, so the true bin is inside the scan.
FINE_SPAN_HZ = 6
#: A channel is a tone when the peak's RMS is at least this share of the channel's RMS.
#: Measured 2026-10-12 on the 43 published files with audio: the lowest tone is 0.979
#: (`mp3/stereo-lr-5s.mp3`, right channel), while two equal tones measure 0.707 and noise 0.04.
MIN_PURITY = 0.9


def power(samples: Sequence[float], rate: int, frequency: float) -> float:
    """Goertzel: the squared magnitude of the signal's transform at one frequency."""
    coeff = 2.0 * math.cos(2.0 * math.pi * frequency / rate)
    s1 = s2 = 0.0
    for sample in samples:
        s1, s2 = sample + coeff * s1 - s2, s1
    return s1 * s1 + s2 * s2 - coeff * s1 * s2


def dominant(samples: Sequence[int], rate: int) -> tuple[float, float] | None:
    """(frequency, purity) of the strongest tone in one channel, or None for silence."""
    count = len(samples)
    if count < rate * COARSE_SECONDS:
        return None
    mean = sum(samples) / count
    centred = [sample - mean for sample in samples]
    energy = sum(value * value for value in centred)
    if energy == 0:
        return None
    coarse = centred[: int(rate * COARSE_SECONDS)]
    steps = int((rate / 2 - MIN_HZ) / COARSE_STEP_HZ)
    candidates = [MIN_HZ + step * COARSE_STEP_HZ for step in range(steps)]
    peak = max(candidates, key=lambda frequency: power(coarse, rate, frequency))
    grid = [round(peak) + offset for offset in range(-FINE_SPAN_HZ, FINE_SPAN_HZ + 1)]
    powers = [power(centred, rate, frequency) for frequency in grid]
    best = max(range(len(grid)), key=powers.__getitem__)
    frequency = float(grid[best])
    if 0 < best < len(grid) - 1 and min(powers[best - 1 : best + 2]) > 0:
        left, middle, right = (math.log(powers[best + k]) for k in (-1, 0, 1))
        curvature = left - 2 * middle + right
        if curvature < 0:
            frequency += 0.5 * (left - right) / curvature
    amplitude = 2 * math.sqrt(max(power(centred, rate, frequency), 0.0)) / count
    purity = (amplitude / math.sqrt(2)) / math.sqrt(energy / count)
    return frequency, purity


def tone_hz(channels: Sequence[Sequence[int]], rate: int) -> list[float | None]:
    """Each channel's tone in Hz to a tenth, or None where no single frequency dominates."""
    measured = [dominant(samples, rate) for samples in channels]
    return [
        round(found[0], 1) if found is not None and found[1] >= MIN_PURITY else None
        for found in measured
    ]
