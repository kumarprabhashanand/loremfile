KMZ is KML inside a ZIP archive, the form Google Earth saves by default. By convention the
archive's first entry is the main KML document, named `doc.kml`, and many readers open the
first KML entry they find.

`kmz/placemarks-10.kmz` holds the ten Point placemarks of the KML fixture, deflate-compressed,
with `doc.kml` as the first entry. Because the placemarks match the [KML](/kml) file, you can
import both into the same tool and compare: a difference in what it shows points at its ZIP
handling rather than at the data.

Use it to test mapping imports, format sniffers that must look inside a ZIP to tell KMZ from
other archives, and upload forms that should accept KMZ while refusing arbitrary ZIP files.
It is also a small, valid ZIP for archive-handling code that does not need anything bigger.
For JSON-based geographic data, see [GeoJSON](/geojson).
