# Meshtastic Coverage — Red Deer, Alberta

~20 nodes heard in about an hour on the local LoRa mesh → SQLite → GeoPandas → ArcGIS Pro coverage map.

## The pipeline

```
airwaves → Meshtastic → Python → SQLite → GeoPandas → ArcGIS Pro → JPEG
```

1. **`meshtastic_sniffer.py`** — listens on USB-serial to a LilyGo T-Echo node and logs every heard packet into `mesh_data.db`: node positions (`POSITION_APP`), device telemetry (`TELEMETRY_APP`: battery, voltage, channel utilization), node names (`NODEINFO_APP`).
2. **`coverage_polygon.py`** — reads the last-known position of every node inside the Red Deer bounding box, draws a 5 km buffer around each one (nominal LoRa range), merges all circles into a single polygon, writes `coverage.geojson` (+ a shapefile for ArcGIS Pro).
3. The polygon is overlaid on a basemap in **ArcGIS Pro** and exported as JPEG. GitHub renders `coverage.geojson` as an interactive zoomable map — open the file above.

## Honest caveat

This is **not** measured RF coverage. The polygon is the union of nominal 5 km buffers around heard nodes — an estimate of where the mesh *could* reach, not a field measurement.

## Files

| File | What it is |
|---|---|
| `meshtastic_sniffer.py` | USB-serial packet sniffer → SQLite (`mesh_data.db`) |
| `coverage_polygon.py` | 5 km buffers + union → GeoJSON / shapefile |
| `requirements.txt` | Python dependencies (`pip install -r requirements.txt`) |
| `.gitignore` | Keeps the raw database and local artefacts out of the repo |
| `coverage.geojson` | Interactive map on GitHub |
| `RedDeerMeshtastic.jpg` | The money shot — map image from the LinkedIn post |

## Run it (Windows)

```bat
pip install meshtastic geopandas
python meshtastic_sniffer.py      :: auto-detects the COM port (override with --port if needed)
python coverage_polygon.py        :: needs mesh_data.db next to the script
```
