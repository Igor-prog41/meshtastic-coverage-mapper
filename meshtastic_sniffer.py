#!/usr/bin/env python3
"""
Meshtastic network sniffer -> SQLite.

Listens to packets received by your node (USB serial) and writes
to a local database:
  - coordinates of all network nodes (POSITION_APP)
  - telemetry (TELEMETRY_APP): battery, voltage, channel utilization
  - node names (NODEINFO_APP)

Production version: same logic on PostgreSQL+PostGIS instead of SQLite.

Run (Windows):
    pip install meshtastic
    python meshtastic_sniffer.py            # auto-detect COM port
"""

import argparse
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id    TEXT PRIMARY KEY,
    short_name TEXT,
    long_name  TEXT,
    last_seen  TEXT
);
CREATE TABLE IF NOT EXISTS positions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id   TEXT NOT NULL,
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    alt       REAL,
    fix_time  TEXT,
    rx_time   TEXT NOT NULL,
    snr       REAL,
    rssi      INTEGER,
    packet_id INTEGER,
    UNIQUE(node_id, packet_id)
);
CREATE TABLE IF NOT EXISTS telemetry (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT NOT NULL,
    battery     INTEGER,
    voltage     REAL,
    ch_util     REAL,
    air_util_tx REAL,
    rx_time     TEXT NOT NULL,
    packet_id   INTEGER,
    UNIQUE(node_id, packet_id)
);
"""


def iso(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path):
        # check_same_thread=False: meshtastic callbacks arrive on the library's
        # background thread while the connection was created on the main one.
        # The lock keeps writes from different threads from interleaving.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    def touch_node(self, node_id, rx_time, short=None, long=None):
        with self.lock:
            self.db.execute(
                """INSERT INTO nodes(node_id, short_name, long_name, last_seen)
                   VALUES(?,?,?,?)
                   ON CONFLICT(node_id) DO UPDATE SET
                     short_name=COALESCE(excluded.short_name, nodes.short_name),
                     long_name=COALESCE(excluded.long_name, nodes.long_name),
                     last_seen=excluded.last_seen""",
                (node_id, short, long, rx_time))
            self.db.commit()

    def add_position(self, node_id, lat, lon, alt, fix_time, rx_time, snr, rssi, pid):
        with self.lock:
            cur = self.db.execute(
                """INSERT OR IGNORE INTO positions
                   (node_id, lat, lon, alt, fix_time, rx_time, snr, rssi, packet_id)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (node_id, lat, lon, alt, fix_time, rx_time, snr, rssi, pid))
            self.db.commit()
            return cur.rowcount > 0

    def add_telemetry(self, node_id, battery, voltage, ch_util, air_tx, rx_time, pid):
        with self.lock:
            cur = self.db.execute(
                """INSERT OR IGNORE INTO telemetry
                   (node_id, battery, voltage, ch_util, air_util_tx, rx_time, packet_id)
                   VALUES(?,?,?,?,?,?,?)""",
                (node_id, battery, voltage, ch_util, air_tx, rx_time, pid))
            self.db.commit()
            return cur.rowcount > 0


def handle_position(store, pkt, rx_time):
    node_id = pkt.get("fromId", "?")
    pid = pkt.get("id")
    pos = (pkt.get("decoded", {}) or {}).get("position", {}) or {}
    # The meshtastic library uses camelCase keys: latitudeI/longitudeI
    # (degrees * 1e7). Older variants kept as fallbacks.
    lat_i = pos.get("latitudeI", pos.get("latitude_i", pos.get("latitude")))
    lon_i = pos.get("longitudeI", pos.get("longitude_i", pos.get("longitude")))
    if lat_i is None or lon_i is None:
        return
    lat = lat_i / 1e7 if abs(lat_i) > 1000 else lat_i
    lon = lon_i / 1e7 if abs(lon_i) > 1000 else lon_i
    alt = pos.get("altitude")
    if store.add_position(node_id, lat, lon, alt, iso(pos.get("time")),
                          rx_time, pkt.get("rxSnr"), pkt.get("rxRssi"), pid):
        print(f"[POS] {node_id}: {lat:.6f}, {lon:.6f}"
              + (f" alt={alt}m" if alt else "")
              + f" snr={pkt.get('rxSnr')} rssi={pkt.get('rxRssi')}", flush=True)


def handle_nodeinfo(store, pkt, rx_time):
    node_id = pkt.get("fromId", "?")
    user = (pkt.get("decoded", {}) or {}).get("user", {}) or {}
    store.touch_node(node_id, rx_time, user.get("shortName"), user.get("longName"))
    if user.get("longName"):
        print(f"[NODE] {node_id} = {user.get('longName')} ({user.get('shortName')})",
              flush=True)


def handle_telemetry(store, pkt, rx_time):
    node_id = pkt.get("fromId", "?")
    pid = pkt.get("id")
    tm = (pkt.get("decoded", {}) or {}).get("telemetry", {}) or {}
    dm = tm.get("deviceMetrics", {}) or {}
    if not dm:
        return
    if store.add_telemetry(node_id, dm.get("batteryLevel"), dm.get("voltage"),
                           dm.get("channelUtilization"), dm.get("airUtilTx"),
                           rx_time, pid):
        print(f"[TLM] {node_id}: batt={dm.get('batteryLevel')}% "
              f"volt={dm.get('voltage')}V", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None,
                    help="COM port, e.g. COM4 (default: auto-detect)")
    ap.add_argument("--db", default="mesh_data.db", help="SQLite database file")
    args = ap.parse_args()

    try:
        from meshtastic.serial_interface import SerialInterface
        from pubsub import pub
    except ImportError:
        sys.exit("Required: pip install meshtastic")

    store = Store(args.db)

    def on_receive(packet, interface=None):
        try:
            rx_time = iso(packet.get("rxTime") or time.time())
            node_id = packet.get("fromId")
            if node_id:
                store.touch_node(node_id, rx_time)
            portnum = (packet.get("decoded", {}) or {}).get("portnum", "")
            pname = portnum if isinstance(portnum, str) else str(portnum)
            if "POSITION" in pname:
                handle_position(store, packet, rx_time)
            elif "NODEINFO" in pname:
                handle_nodeinfo(store, packet, rx_time)
            elif "TELEMETRY" in pname:
                handle_telemetry(store, packet, rx_time)
        except Exception as e:  # never let one bad packet kill the listener
            print(f"[ERR] {e}", flush=True)

    print("Connecting to node...", flush=True)
    iface = SerialInterface(devPath=args.port)
    pub.subscribe(on_receive, "meshtastic.receive")
    print(f"Listening to the airwaves, writing to {args.db}. Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        iface.close()


if __name__ == "__main__":
    main()
