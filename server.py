#!/usr/bin/env python3
"""Tiny AirTag tracker: stdlib HTTP server + SQLite. Run: python3 server.py"""
import json
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "airtags.db"


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, note TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS sightings (
            id INTEGER PRIMARY KEY, tag_id INTEGER NOT NULL REFERENCES tags(id),
            lat REAL NOT NULL, lon REAL NOT NULL, ts INTEGER NOT NULL,
            note TEXT DEFAULT '');
        """
    )
    return con


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        elif self.path == "/api/tags":
            with db() as con:
                rows = con.execute(
                    """SELECT t.id, t.name, t.note, s.lat, s.lon, s.ts, s.note AS sighting_note
                       FROM tags t LEFT JOIN sightings s ON s.id = (
                           SELECT id FROM sightings WHERE tag_id = t.id ORDER BY ts DESC LIMIT 1)
                       ORDER BY t.name"""
                ).fetchall()
            self.send_json([dict(r) for r in rows])
        elif self.path.startswith("/api/tags/") and self.path.endswith("/history"):
            tag_id = int(self.path.split("/")[3])
            with db() as con:
                rows = con.execute(
                    "SELECT lat, lon, ts, note FROM sightings WHERE tag_id = ? ORDER BY ts",
                    (tag_id,),
                ).fetchall()
            self.send_json([dict(r) for r in rows])
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            data = self.body()
            if self.path == "/api/tags":
                name = str(data["name"]).strip()
                if not name:
                    raise ValueError("name required")
                with db() as con:
                    cur = con.execute(
                        "INSERT INTO tags (name, note) VALUES (?, ?)",
                        (name, str(data.get("note", ""))),
                    )
                self.send_json({"id": cur.lastrowid}, 201)
            elif self.path.startswith("/api/tags/") and self.path.endswith("/sightings"):
                tag_id = int(self.path.split("/")[3])
                lat, lon = float(data["lat"]), float(data["lon"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError("lat/lon out of range")
                with db() as con:
                    con.execute(
                        "INSERT INTO sightings (tag_id, lat, lon, ts, note) VALUES (?,?,?,?,?)",
                        (tag_id, lat, lon, int(data.get("ts", time.time())), str(data.get("note", ""))),
                    )
                self.send_json({"ok": True}, 201)
            else:
                self.send_json({"error": "not found"}, 404)
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
            self.send_json({"error": str(e)}, 400)

    def do_DELETE(self):
        if self.path.startswith("/api/tags/"):
            tag_id = int(self.path.split("/")[3])
            with db() as con:
                con.execute("DELETE FROM sightings WHERE tag_id = ?", (tag_id,))
                con.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    db().close()
    print("AirTag tracker on http://127.0.0.1:8000")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
