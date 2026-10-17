"""Meshtastic network coverage polygon.

Reads the latest node positions from mesh_data.db (Red Deer bounding box),
draws a nominal-radius circle around each point (5 km buffer, computed in
meters via UTM 12N) and merges all circles into a single polygon with no
inner boundaries (union). Saves coverage.geojson.

The shapefile opens in ArcGIS Pro with no fuss (Map -> Add Data);
the GeoJSON will be used later for Leaflet/GitHub.

Dependencies: pip install geopandas
"""

import os
import sqlite3

import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import unary_union

DB = "mesh_data.db"      # sniffer database; place next to the script or set a path
OUT_GEOJSON = "coverage.geojson"
SHP_DIR = "coverage_shp"                        # a shapefile is a set of files, lives in its own folder
OUT_SHP = os.path.join(SHP_DIR, "coverage.shp")  # for ArcGIS Pro
BUFFER_M = 5000          # nominal coverage radius, meters

# Red Deer bounding box
LAT_MIN, LAT_MAX = 52.20, 52.35
LON_MIN, LON_MAX = -113.95, -113.75


def load_points(db_path):
    con = sqlite3.connect(db_path)
    rows = con.execute(
        """
        SELECT p.lat AS latitude, p.lon AS longitude, MAX(p.rx_time) AS last_seen
        FROM positions p
        WHERE p.lat BETWEEN ? AND ?
          AND p.lon BETWEEN ? AND ?
        GROUP BY p.node_id
        """,
        (LAT_MIN, LAT_MAX, LON_MIN, LON_MAX),
    ).fetchall()
    con.close()
    # shapely wants (x, y) = (lon, lat)
    return [(lon, lat) for lat, lon, _ in rows]


def main():
    pts = load_points(DB)
    print(f"Points: {len(pts)}")
    if not pts:
        print("No points inside the bounding box.")
        return

    gdf = gpd.GeoDataFrame(geometry=[Point(lon, lat) for lon, lat in pts],
                           crs="EPSG:4326")

    circles = gdf.to_crs("EPSG:32612").buffer(BUFFER_M)  # UTM 12N: meters
    merged = unary_union(circles)          # merge overlaps, drop inner borders

    out = gpd.GeoDataFrame({"name": ["coverage"]}, geometry=[merged],
                           crs="EPSG:32612").to_crs("EPSG:4326")
    out.to_file(OUT_GEOJSON, driver="GeoJSON")
    os.makedirs(SHP_DIR, exist_ok=True)
    out.to_file(OUT_SHP)  # shapefile: ArcGIS Pro opens it with no fuss
    print(f"Done: {OUT_GEOJSON}, {OUT_SHP} ({out.geometry.geom_type.iloc[0]})")


if __name__ == "__main__":
    main()
