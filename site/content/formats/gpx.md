GPX is the XML format GPS devices and fitness apps use to exchange tracks, routes and
waypoints. `gpx/track-100-points.gpx` is a GPX 1.1 track: one track, one segment and 100
points, each with an elevation and a timestamp.

The timestamps increase monotonically, so software that computes duration, speed or pace gets
sensible numbers, and an importer that sorts or removes duplicate points has an order to
preserve. The elevations let you test elevation profiles and total ascent.

Use it to test fitness and mapping apps, GPX importers and converters, and upload forms that
accept activity files. Because GPX is XML with a namespace, it also checks that a parser
handles the GPX 1.1 namespace rather than matching bare element names, which is the most
common reason a GPX file "has no points" in a hand-written importer. Related formats:
[GeoJSON](/geojson) and [KML](/kml).
