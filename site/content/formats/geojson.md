GeoJSON is JSON for geographic features, and the format most web mapping libraries read
first. `geojson/points-100.geojson` is a FeatureCollection of 100 Point features, each with a
name, a category, an elevation and a timestamp.

Every point lies inside a bounding box over the South Atlantic, over open ocean. That is
deliberate: no invented data sits on top of a real place, so a test screenshot never appears
to label a real town or address with made-up values.

Use it to test map rendering and clustering, spatial queries, feature property handling, and
upload forms that accept geographic data. GeoJSON orders coordinates as longitude, then
latitude; a map that shows these points anywhere other than the South Atlantic has swapped
them. The file is plain UTF-8 JSON, so it also works as input for a generic JSON parser.
Related formats: [GPX](/gpx), [KML](/kml) and [JSON](/json).
