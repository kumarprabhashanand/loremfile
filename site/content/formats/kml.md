KML is the XML format of Google Earth, and still a common way to share placemarks, paths and
polygons between mapping tools. `kml/placemarks-10.kml` is a KML 2.2 document with ten Point
placemarks, each with a name and a description.

It is deliberately small and plain, so it isolates the basics a KML reader has to get right:
the KML 2.2 namespace, the `Document` and `Placemark` structure, and coordinates written as
longitude, latitude and optional altitude, in that order. A viewer that places the points
somewhere unexpected has most likely swapped the axes.

Use it to test map imports in GIS tools and web maps, converters to GeoJSON or GPX, and
upload forms that accept KML. Its zipped counterpart is the [KMZ](/kmz) file, which holds the
same placemarks; for other geographic formats see [GeoJSON](/geojson) and [GPX](/gpx).
