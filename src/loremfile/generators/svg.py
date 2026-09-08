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
