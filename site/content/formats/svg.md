SVG is vector graphics written as XML, which makes it both an image and a document that
could, in principle, carry script. These files are hand-written with no script, no event
handlers and no external references, and they are served with a sandbox
Content-Security-Policy, so they render their shapes but can execute nothing.

`svg/simple-shapes.svg` draws a rectangle, a circle and a polyline path, with explicit width
and height attributes. Those attributes matter: an SVG without them has no intrinsic size,
and image tools disagree about how large to render it.

`svg/with-embedded-png.svg` contains a PNG as a data URI and no other raster content, so
nothing is fetched from the network when it renders. It tests whether a sanitiser keeps safe
embedded images, and whether a rasteriser handles data URIs.

Use them for image upload forms, SVG sanitisers, rasterisers and icon pipelines. Related
formats: [PNG](/png) and [WebP](/webp).
