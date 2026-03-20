# 3D Printer — Bambu Lab P2S

## Build Volume
| Axis | mm  |
|------|-----|
| X    | 256 |
| Y    | 256 |
| Z    | 256 |

Build plate: 256 × 256 mm (square).

## Filament
- Diameter: 1.75 mm
- Nozzle: 0.4 mm (default); 0.2 / 0.6 / 0.8 mm optional
- Max hotend temp: 300 °C
- Enclosed chamber — supports ABS, ASA, PA, PC etc.

## 3MF Export Layout (enclosure viewer → `↓ 3MF`)

The exported file contains two separate manifold objects:

| Part | 3MF orientation |
|------|-----------------|
| Body | Long axis (W) along X; floor at Z = 0 |
| Lid  | Same X centre as body; offset +Y by D + 5 mm; top face at Z = t (wall thickness) |

### Footprint at default slider values (W=140, H=90, D=90, t=2)
- Body: 140 × 90 mm (X × Y)
- Lid:  140 × 90 mm, placed at Y = 95…185 mm
- Combined: 140 mm (X) × 185 mm (Y) — fits on 256 × 256 ✓

### Footprint at maximum slider values (W=200, H=130, D=140, t=?)
- Body: 200 × 140 mm — fits (200 ≤ 256, 140 ≤ 256) ✓
- Lid: placed at Y = 145…285 mm — lid far edge exceeds plate at D_max=140.
  If this occurs, separate the lid into a second print job.

### Print orientation
- Body: floor on build plate, walls print upward. No supports required for side-wall
  holes (camera, PIR, speaker, USB) if hole diameter ≥ 3 mm and wall is vertical.
- Lid: printed flat (t mm tall). Essentially no print time.

### Non-manifold warning
The body is an open-top tray (no top wall — the lid is a separate part).
Bambu Studio will report "non-manifold" but **auto-repairs and slices correctly**.
This is standard enclosure geometry; the warning can be dismissed.
Closing the top to suppress the warning would make the enclosure non-functional
(components cannot be installed).

## Coordinate mapping (Three.js Y-up → 3MF Z-up)

```
Three.js (x, y, z)  →  3MF (x, −z, y)
```

- 3MF X = Three.js X  (enclosure width W — long axis)
- 3MF Y = −Three.js Z (enclosure depth D)
- 3MF Z = Three.js Y  (print height H)
