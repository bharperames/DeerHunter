#!/usr/bin/env python3
"""
parse_brd.py — Extract PCB mount-hole positions from Eagle .brd files.

Outputs src/web/static/pcb_data.json with exact mount hole positions for
components whose source files are publicly available.  The viewer merges
this data into COMP_SPECS at startup, replacing estimated values.

Run:  python tools/parse_brd.py

Sources:
  MAX98357A  — adafruit/Adafruit-MAX98357-I2S-Amp-Breakout (Eagle .brd, XML)
  Pi Zero 2W — RPi mechanical drawing (known authoritative values hardcoded)
  Camera v3  — RPi mechanical drawing (known authoritative values hardcoded)
"""

import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

OUT_PATH = Path(__file__).parent.parent / "src" / "web" / "static" / "pcb_data.json"

# ── Eagle .brd parsing ────────────────────────────────────────────────────────

def parse_eagle_brd(xml_bytes: bytes) -> dict:
    """Parse an Eagle .brd XML file.  Returns dict with 'outline' and 'mountHoles'."""
    root = ET.fromstring(xml_bytes)

    # Eagle XML namespace may or may not be present; use a helper
    def find_all(node, tag):
        # Try with and without namespace
        results = list(node.iter(tag))
        if not results:
            for ns in ('{}', '{http://eagle.cadsoft.de/}'):
                results = list(node.iter(f'{ns}{tag}'))
                if results:
                    break
        return results

    # ── Board outline (layer 20 wires) ───────────────────────────────────────
    outline_pts = set()
    outline_edges = []
    for wire in find_all(root, 'wire'):
        if wire.get('layer') == '20':
            x1 = float(wire.get('x1', 0))
            y1 = float(wire.get('y1', 0))
            x2 = float(wire.get('x2', 0))
            y2 = float(wire.get('y2', 0))
            outline_pts.add((x1, y1))
            outline_pts.add((x2, y2))
            outline_edges.append(((x1, y1), (x2, y2)))

    # Build convex-ish outline polygon by sorting points around centroid
    if outline_pts:
        pts = list(outline_pts)
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        import math
        pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    else:
        pts = []

    # Normalise: shift so board origin is at (0,0), then centre
    if pts:
        min_x = min(p[0] for p in pts)
        min_y = min(p[1] for p in pts)
        pts = [(p[0] - min_x, p[1] - min_y) for p in pts]
        max_x = max(p[0] for p in pts)
        max_y = max(p[1] for p in pts)
        # Convert to centre-relative coords (x right, z down — same sign as COMP_SPECS)
        outline = [{"x": round(p[0] - max_x / 2, 4), "z": round(p[1] - max_y / 2, 4)}
                   for p in pts]
    else:
        outline = []

    # ── Mount holes — <hole> elements (non-plated drills) ───────────────────
    # These are the non-plated mounting holes used for standoffs.
    mount_holes = []

    # Board bounds for centering
    if outline_pts:
        raw_pts = list(outline_pts)
        raw_min_x = min(p[0] for p in raw_pts)
        raw_min_y = min(p[1] for p in raw_pts)
        raw_max_x = max(p[0] for p in raw_pts)
        raw_max_y = max(p[1] for p in raw_pts)
        board_cx = (raw_min_x + raw_max_x) / 2
        board_cy = (raw_min_y + raw_max_y) / 2
    else:
        board_cx = board_cy = 0

    for hole in find_all(root, 'hole'):
        hx = float(hole.get('x', 0))
        hy = float(hole.get('y', 0))
        drill = float(hole.get('drill', 0))
        mount_holes.append({
            "x":     round(hx - board_cx, 4),
            "z":     round(hy - board_cy, 4),
            "drill": round(drill, 4),
        })

    # ── Also check <element> entries with mounting-hole package names ─────────
    MOUNT_PKG_KEYWORDS = ('mount', 'hole', 'mh', 'standoff', 'via')
    element_holes = []
    for elem in find_all(root, 'element'):
        pkg = (elem.get('package') or '').lower()
        if any(k in pkg for k in MOUNT_PKG_KEYWORDS):
            ex = float(elem.get('x', 0))
            ey = float(elem.get('y', 0))
            element_holes.append({
                "x":     round(ex - board_cx, 4),
                "z":     round(ey - board_cy, 4),
                "drill": None,  # drill size in package, not easily extracted here
                "name":  elem.get('name', ''),
                "package": elem.get('package', ''),
            })

    # Prefer <hole> elements; fall back to element-based if none found
    if not mount_holes and element_holes:
        mount_holes = [{k: v for k, v in h.items() if k != 'name' and k != 'package'}
                       for h in element_holes]

    return {
        "outline":      outline,
        "mountHoles":   mount_holes,
        "_elementHoles": element_holes,  # debug — not used by viewer
        "_boardSize":   {"w": round(raw_max_x - raw_min_x, 4) if outline_pts else 0,
                         "h": round(raw_max_y - raw_min_y, 4) if outline_pts else 0},
    }


def fetch_url(url: str) -> bytes:
    print(f"  Fetching: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "DeerHunter-parse-brd/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    print(f"  Downloaded {len(data):,} bytes")
    return data


# ── MAX98357A (Adafruit #3006) ────────────────────────────────────────────────

MAX_BRD_URL = (
    "https://raw.githubusercontent.com/adafruit/"
    "Adafruit-MAX98357-I2S-Amp-Breakout/master/"
    "Adafruit%20MAX98357%20Breakout.brd"
)
MAX_BRD_FALLBACK_URL = (
    "https://raw.githubusercontent.com/adafruit/"
    "Adafruit-MAX98357-I2S-Amp-Breakout/master/"
    "Adafruit%20MAX98357%20I2S%20Amp%20Breakout.brd"
)


def build_max98357a(git_sha: str = "HEAD") -> dict:
    print("\n── MAX98357A (Eagle .brd) ──────────────────────────────")
    data = None
    for url in [MAX_BRD_URL, MAX_BRD_FALLBACK_URL]:
        try:
            data = fetch_url(url)
            source_url = url
            break
        except Exception as exc:
            print(f"  Warning: {exc}")

    if data is None:
        print("  ERROR: Could not download .brd — using fallback estimate")
        return {
            "outline": [
                {"x": -9.525, "z": -8.89},
                {"x":  9.525, "z": -8.89},
                {"x":  9.525, "z":  8.89},
                {"x": -9.525, "z":  8.89},
            ],
            "mountHoles": [{"x": -7.53, "z": 0, "drill": 2.7},
                           {"x":  7.53, "z": 0, "drill": 2.7}],
            "source": "fallback-estimate",
            "_note": "Download failed; using prior estimate",
        }

    parsed = parse_eagle_brd(data)

    bw = parsed["_boardSize"]["w"]  # Eagle X extent = 17.78 mm
    bh = parsed["_boardSize"]["h"]  # Eagle Y extent = 19.05 mm

    print(f"  Board size:   {bw:.3f} × {bh:.3f} mm  (Eagle X × Eagle Y)")
    print(f"  Raw holes:    {parsed['mountHoles']}")
    if parsed['_elementHoles']:
        print(f"  Elem holes:   {parsed['_elementHoles']}")

    # Axis mapping for MAX98357A — DIRECT (Eagle X → scene X, Eagle Y → scene Z):
    #
    #   parse_eagle_brd outputs: hole["x"] = Eagle X offset from board centre
    #                            hole["z"] = Eagle Y offset from board centre
    #
    #   Verification via product photo (max98357a.jpg, 640×674 portrait):
    #     - Screw terminals (SPK) at photo TOP, I2S header at photo BOTTOM
    #     - Two holes at TOP-LEFT (Eagle X=-6.35) and TOP-RIGHT (Eagle X=+6.35)
    #     - Both holes at same Eagle Y = +6.985 from centre (near SPK end)
    #     - imgTransform {rotate:180} flips photo → holes appear BOTTOM-LEFT/RIGHT
    #     - Canvas BOTTOM = scene z=+8.89 (SPK/+Z direction) ✓
    #     - Canvas LEFT/RIGHT = scene x=∓6.35 (direct Eagle X → scene X) ✓
    #
    #   Using direct mapping (no swap) gives holes at {x:±6.35, z:+6.985} which
    #   aligns with what the product photo shows after rotate:180.
    #
    #   M2.5 plated mounting hole — drill 2.75 mm nominal (M2.5 clearance).
    raw_holes = parsed["mountHoles"] or parsed.get("_elementHoles", [])
    scene_holes = [
        {"x": round(h["x"], 4), "z": round(h["z"], 4), "drill": 2.75}
        for h in raw_holes
    ]
    print(f"  Scene holes:  {scene_holes}  (direct Eagle X→scene X, Eagle Y→scene Z)")

    # Board outline in scene coords (direct mapping)
    scene_outline = [
        {"x": round(pt["x"], 4), "z": round(pt["z"], 4)}
        for pt in parsed["outline"]
    ]

    result = {
        "outline":   scene_outline,
        "boardSize": {"w": bw, "h": bh},  # Eagle X extent in scene X, Eagle Y in scene Z
        "mountHoles": scene_holes,
        "source":    f"adafruit/Adafruit-MAX98357-I2S-Amp-Breakout @ {source_url}",
    }
    return result


# ── Pi Zero 2W (authoritative RPi mechanical drawing) ────────────────────────
# Source: datasheets.raspberrypi.com/pizero2w/raspberry-pi-zero-2-w-mechanical-drawing.pdf
# PCB: 65 × 30 mm.  4× M2.5 holes, 3.5 mm from each edge.
#   X C-C: 65 - 2×3.5 = 58.0 mm  →  ±29.0 mm from PCB centre
#   Z C-C: 30 - 2×3.5 = 23.0 mm  →  ±11.5 mm from PCB centre
# M2.5 drill: 2.75 mm nominal

def build_pi_zero_2w() -> dict:
    print("\n── Pi Zero 2W (RPi mechanical drawing) ─────────────────")
    holes = [
        {"x": -29.0, "z": -11.5, "drill": 2.75},
        {"x":  29.0, "z": -11.5, "drill": 2.75},
        {"x": -29.0, "z":  11.5, "drill": 2.75},
        {"x":  29.0, "z":  11.5, "drill": 2.75},
    ]
    print(f"  Holes (authoritative): {holes}")
    return {
        "outline": [
            {"x": -32.5, "z": -15.0},
            {"x":  32.5, "z": -15.0},
            {"x":  32.5, "z":  15.0},
            {"x": -32.5, "z":  15.0},
        ],
        "boardSize": {"w": 65.0, "h": 30.0},
        "mountHoles": holes,
        "source": "datasheets.raspberrypi.com/pizero2w/raspberry-pi-zero-2-w-mechanical-drawing.pdf",
    }


# ── Pi Camera Module v3 NoIR (RPi mechanical drawing) ────────────────────────
# Source: datasheets.raspberrypi.com (Camera Module v3 mechanical)
# PCB: 25 × 24 mm.  4× M2 holes, 2.0 mm from each edge.
#   X C-C: 25 - 2×2.0 = 21.0 mm  →  ±10.5 mm from PCB centre
#   Z C-C: 24 - 2×2.0 = 20.0 mm  →  ±10.0 mm from PCB centre
# M2 drill: 2.2 mm nominal

def build_camera_v3_noir() -> dict:
    print("\n── Camera Module v3 NoIR (RPi mechanical drawing) ──────")
    holes = [
        {"x": -10.5, "z": -10.0, "drill": 2.2},
        {"x":  10.5, "z": -10.0, "drill": 2.2},
        {"x": -10.5, "z":  10.0, "drill": 2.2},
        {"x":  10.5, "z":  10.0, "drill": 2.2},
    ]
    print(f"  Holes (RPi mechanical): {holes}")
    return {
        "outline": [
            {"x": -12.5, "z": -12.0},
            {"x":  12.5, "z": -12.0},
            {"x":  12.5, "z":  12.0},
            {"x": -12.5, "z":  12.0},
        ],
        "boardSize": {"w": 25.0, "h": 24.0},
        "mountHoles": holes,
        "source": "datasheets.raspberrypi.com (Camera Module v3 mechanical drawing)",
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("parse_brd.py — PCB data extractor")
    print("=" * 50)

    pcb_data = {
        "max98357a":    build_max98357a(),
        "pi_zero_2w":   build_pi_zero_2w(),
        "camera_v3_noir": build_camera_v3_noir(),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(pcb_data, f, indent=2)

    print(f"\n✓ Written: {OUT_PATH}")
    print("\nSummary of mount hole positions:")
    for comp_id, data in pcb_data.items():
        print(f"  {comp_id}:")
        for h in data["mountHoles"]:
            drill_str = f"  drill={h['drill']}" if h.get('drill') else ""
            print(f"    x={h['x']:+.3f}  z={h['z']:+.3f}{drill_str}")


if __name__ == "__main__":
    main()
