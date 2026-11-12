"""SVG fixtures (docs/05 §3.2).

Hand-written markup, deliberately. **No `<script>`, no event handlers, no external
references** — `validators/policy.py` rejects all three, and SVG is the format where a
careless fixture would be an actual security problem rather than a cosmetic one.

Served with the sandbox CSP (docs/03 §4.2), so an SVG opened directly renders its own
shapes and embedded images but cannot execute anything.
"""

from __future__ import annotations

import base64
import io

from loremfile.generators.base import GeneratorContext, generator
from loremfile.generators.image import test_card

HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'


@generator()
def simple_shapes(_ctx: GeneratorContext, *, width: int = 200, height: int = 200) -> bytes:
    """Rect, circle and path with explicit width and height attributes."""
    body = f"""{HEADER}<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
     viewBox="0 0 {width} {height}">
  <title>loremfile.dev simple shapes</title>
  <desc>A rectangle, a circle and a path. No script, no external references.</desc>
  <rect x="10" y="10" width="80" height="60" fill="#3b6ea5" stroke="#1f3a5f"
        stroke-width="2" rx="6"/>
  <circle cx="150" cy="50" r="35" fill="#d97706" stroke="#7c4a06" stroke-width="2"/>
  <path d="M 20 120 L 60 180 L 100 120 L 140 180 L 180 120" fill="none"
        stroke="#166534" stroke-width="4" stroke-linejoin="round"/>
  <line x1="10" y1="190" x2="190" y2="190" stroke="#6b7280" stroke-width="1"/>
</svg>
"""
    return body.encode("utf-8")


@generator()
def with_embedded_png(_ctx: GeneratorContext, *, width: int = 200, height: int = 200) -> bytes:
    """An SVG whose only image is a PNG data URI — no external reference.

    The PNG is generated here rather than pulled from a published fixture, so the file
    is self-contained and carries no dependency edge.
    """
    card = test_card(64, 64, "RGB")
    buffer = io.BytesIO()
    card.save(buffer, format="PNG", optimize=False)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    body = f"""{HEADER}<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <title>loremfile.dev SVG with an embedded PNG</title>
  <desc>The raster image is a data URI, so nothing is fetched from the network.</desc>
  <rect width="{width}" height="{height}" fill="#f3f4f6"/>
  <image x="20" y="20" width="64" height="64"
         xlink:href="data:image/png;base64,{encoded}"/>
  <image x="116" y="116" width="64" height="64"
         href="data:image/png;base64,{encoded}"/>
  <text x="20" y="110" font-family="monospace" font-size="12" fill="#111827">
    embedded PNG, twice
  </text>
</svg>
"""
    return body.encode("utf-8")


@generator()
def text_and_gradient(_ctx: GeneratorContext) -> bytes:
    """A linear and a radial gradient behind three lines of text at different sizes."""
    body = f"""{HEADER}<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"
     viewBox="0 0 320 200">
  <title>loremfile.dev text and gradients</title>
  <desc>Two gradients and three lines of text. No script, no external references.</desc>
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#1e3a8a"/>
      <stop offset="1" stop-color="#93c5fd"/>
    </linearGradient>
    <radialGradient id="sun" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#fef08a"/>
      <stop offset="1" stop-color="#f97316" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="320" height="200" fill="url(#sky)"/>
  <circle cx="240" cy="60" r="44" fill="url(#sun)"/>
  <text x="20" y="64" font-family="sans-serif" font-size="32" font-weight="bold"
        fill="#ffffff">Lorem ipsum</text>
  <text x="20" y="104" font-family="serif" font-size="18" font-style="italic"
        fill="#f8fafc">dolor sit amet, consectetur</text>
  <text x="300" y="184" font-family="monospace" font-size="12" text-anchor="end"
        fill="#0f172a">right-aligned</text>
</svg>
"""
    return body.encode("utf-8")


@generator()
def viewbox_only(_ctx: GeneratorContext) -> bytes:
    """A viewBox and no width or height: the file has no intrinsic size and fills its container."""
    body = f"""{HEADER}<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"
     preserveAspectRatio="xMidYMid meet">
  <title>loremfile.dev viewBox only</title>
  <desc>No width and no height: the viewBox alone sets the aspect ratio.</desc>
  <rect x="0" y="0" width="400" height="300" fill="#e2e8f0"/>
  <rect x="20" y="20" width="360" height="260" fill="none" stroke="#475569" stroke-width="4"/>
  <circle cx="200" cy="150" r="90" fill="#38bdf8" stroke="#0369a1" stroke-width="6"/>
  <path d="M 110 150 L 290 150 M 200 60 L 200 240" stroke="#0c4a6e" stroke-width="4"/>
</svg>
"""
    return body.encode("utf-8")


#: Six 24 by 24 icons drawn from plain shapes: (id, markup inside the symbol).
ICONS = (
    ("square", '<rect x="4" y="4" width="16" height="16" rx="2"/>'),
    ("circle", '<circle cx="12" cy="12" r="8"/>'),
    ("triangle", '<path d="M 12 4 L 21 20 L 3 20 Z"/>'),
    ("cross", '<path d="M 5 5 L 19 19 M 19 5 L 5 19"/>'),
    ("plus", '<path d="M 12 4 V 20 M 4 12 H 20"/>'),
    ("menu", '<path d="M 4 7 H 20 M 4 12 H 20 M 4 17 H 20"/>'),
)
ICON_SIDE = 24


@generator()
def icon_sheet(_ctx: GeneratorContext) -> bytes:
    """A sprite: six `<symbol>` icons, each with a 24 by 24 viewBox, each shown once by `<use>`."""
    width = ICON_SIDE * len(ICONS)
    symbols = "\n".join(
        f'    <symbol id="icon-{name}" viewBox="0 0 {ICON_SIDE} {ICON_SIDE}">{shape}</symbol>'
        for name, shape in ICONS
    )
    uses = "\n".join(
        f'  <use href="#icon-{name}" x="{index * ICON_SIDE}" y="0" '
        f'width="{ICON_SIDE}" height="{ICON_SIDE}"/>'
        for index, (name, _) in enumerate(ICONS)
    )
    body = f"""{HEADER}<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{ICON_SIDE}"
     viewBox="0 0 {width} {ICON_SIDE}" fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round" color="#1f2937">
  <title>loremfile.dev icon sheet</title>
  <desc>Six 24 by 24 icons, each defined once as a symbol and shown with use.</desc>
  <defs>
{symbols}
  </defs>
{uses}
</svg>
"""
    return body.encode("utf-8")
