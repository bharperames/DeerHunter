# Changelog

All notable changes to DeerHunter are documented here.

---

## [Unreleased] — 2026-03-21

### Enclosure — Unified CSG geometry + print-layout scene

#### Architecture: Dual representation eliminated
The enclosure viewer previously maintained two separate geometry paths: a piecewise visual scene (5× `makeWall`, `addStandoffs`, `mountGroup`) and a separate CSG export geometry. These diverged silently — changes to one didn't update the other.

Both paths have been merged into a single CSG pipeline. The same geometry is rendered in the scene and exported as STL/3MF. What you see is what you print.

**Removed:**
- `mountGroup` and "Show mounting posts" checkbox — all boss geometry is now part of the printed CSG body
- `makeWall` / `addStandoffs` visual-only geometry blocks
- Separate visual battery cradle, TP4056 cradle, speaker boss cylinders
- Duplicate wall/lid construction code

**Added:**
- `csgSubtract` null-guard: `if (result.geometry) brush = result` — prevents crash when three-bvh-csg returns a null-geometry result
- `toNI` helper strips UV/color attributes before `mergeGeometries` — fixes `mergeGeometries returns null` crash caused by attribute mismatch between geometries
- Null guard on `mergedBody`: throws a clear error if merge fails rather than crashing downstream

#### Print-layout scene
The scene now shows both parts in print-plate orientation (mirroring Bambu Studio):
- **Body**: open-top tray at Y=0..H, interior visible from above
- **Lid**: flat on ground plane at Y=0..t, placed 5mm beside the body in −Z — no longer floating above the body at assembly height

This makes the interior visible without adjusting the camera and shows exactly how parts will sit on the build plate.

#### Corner boss pads (lid mounting)
Previously: 4× full-height cylinders (H−t ≈ 57mm tall) rising from the floor to the lid — pilot holes ran the full column length.

Now: 4× **12×12×13mm rectangular pads** integrated into the wall corners:
- Flush against both adjacent wall interior faces (no gap)
- Only 13mm tall (SCREW_DEPTH=12mm + 1mm blind bottom)
- Pilot hole opens at the top, blind 12mm down — M3 self-tapping
- Lid clearance holes (Ø3.4mm) unchanged; positions match pad centres

#### Pilot hole depth cap
`floorBoss` now caps pilot hole depth to `min(bH − 1mm, SCREW_DEPTH=12mm)`. All floor bosses (Pi Zero, amp, corners) previously drilled the full boss height. Short bosses (8mm Pi/Amp standoffs) are unaffected; tall corner columns were the visible issue.

#### TP4056 charger placement + lid window
- TP4056 constants (`tpX`, `tpZ`) hoisted above the lid CSG section so the lid can reference them
- USB-C port faces right wall → 3.6×10mm slot punched through right wall
- Charge LEDs face up → 12×5mm window cut into lid at `(tpX+6, tpZ)` — visible through lid without removing it
- Friction cradle (4 rails) added to `cradleGeos` so it appears in the exported STL/3MF

#### CSG crash fix
`csgSubtract` returned `brush.geometry` which could be null if three-bvh-csg's `evaluate()` produced a null-geometry result on degenerate inputs (coplanar faces, zero-thickness holes). Now returns `brush.geometry || baseGeo` and skips `brush = result` when `result.geometry` is null.

---

### Enclosure — Component dimension corrections

#### Speaker: replaced wrong component
The BOM listed Adafruit #1890 (Mini Metal Speaker). Research confirmed this is a **28mm** bare wired speaker with no mounting holes — incompatible with the enclosure's 40mm circular bolt-circle boss geometry.

Replaced with **Visaton K 50 WP 8Ω** (Art. 2915), verified from TME datasheet PDF (2026-03):

| Parameter | Was (Adafruit #1890) | Now (Visaton K 50 WP) |
|-----------|---------------------|----------------------|
| Outer diameter | 40mm (assumed) | **50mm** |
| Panel cutout | 24mm | **45.5mm** |
| Body depth | 20mm | **18mm** |
| Mount pattern | 4× M3 on Ø32mm circle (invented) | **4× M4 Ø4.5mm on □31.5mm square** |
| Weatherproof | No | **IP65** |
| Temp range | Unknown | **−40°C to +80°C** |
| UV resistance | No | **Yes (ABS basket)** |

Speaker boss geometry updated accordingly:
- `SPK_R`: 20 → **25** (50mm OD)
- `SPK_CONE_R`: 12 → **22.75** (Ø45.5mm cutout)
- `SPK_DEPTH`: 20 → **18**
- Boss pattern: 4× `rightWallBoss` on circular `SPK_BOLT_R` angle loop → 4× `rightWallBoss` on explicit **□31.5mm square** `[[y+hs,z+hs],[y+hs,z-hs],[y-hs,z+hs],[y-hs,z-hs]]`
- Boss OD: 7mm (M3) → **9mm** (M4)
- Pilot radius: 1.15mm → **1.7mm** (M4)
- Export wall hole: `SPK_R+1` → **`SPK_CONE_R`** (22.75mm)
- Dimension label: `Ø42.0mm` → **`Ø45.5mm`**

#### MAX98357A amplifier: PCB dimensions corrected
Previous code used 22.86×17.78mm (0.9"×0.7" from learning guide). The Eagle `.brd` file from `adafruit/Adafruit-MAX98357-I2S-Amp-Breakout` was downloaded and the board outline (layer 20 wires) read directly:

```
X: 0 → 17.78mm  (short axis)
Y: 0 → 19.05mm  (long axis)
```

Adafruit product page confirms 19.4×17.8mm. Changes:
- `AMP_W`: 22.86 → **19.05mm**
- `mountHoles` X offset: ±9.43mm → **±7.53mm** (estimated 2mm from each long-axis edge; `<elements>` section was truncated in fetch — not confirmed from file)
- Display label: `22.9×17.8mm` → `19.1×17.8mm`
- `COMP_SPECS.max98357a` comment updated

#### PIR sensor: mount holes corrected
Previous `mountHoles` placed bosses at `z:0` (PCB centre height). On the HC-SR501, the two M2 holes are near the **bottom** edge of the PCB (3.5mm from edge = −8.5mm from centre). Boss centres were overlapping the Fresnel dome cutout.

- `mountHoles`: `[{x:−14,z:0},{x:14,z:0}]` → `[{x:−14,z:−8.5},{x:14,z:−8.5}]`
- Boss clearance from dome centre verified: √(14²+8.5²) − 2.5 = 13.9mm > dome radius 13.1mm ✓

---

### buildme.md — Assembly guide updates

- **BOM row 5**: `Mini Speaker 8Ω 0.5W` → `Visaton K 50 WP 8Ω (Art. 2915) — IP65, 50mm, 2W/3W`
- **BOM rows added**:
  - Row 18: M3 × 12mm self-tapping screws ×4 (lid to corner boss pads)
  - Row 19: M4 × 12mm self-tapping screws ×4 (speaker to right wall bosses)
- **Step 8**: Updated speaker mount description — M4 (was M3), □31.5mm square pattern (was 16mm bolt circle)
- **Step 14**: Updated lid closing — "corner boss pads" (was "corner boss columns"), M3 × 12mm self-tapping

---

### components.html — Component cards updated

- **Speaker card**: Replaced Adafruit #1890 entry with Visaton K 50 WP — title, model, specs (IP65, 50mm, M4 mount, temp range), buy link updated
- **MAX98357A card**: Dimensions updated to `19.1×17.8mm`; added `2× M2.5 oval mount slots` spec; removed redundant spec line

---

### Known gaps (not yet resolved)

These items are estimated, not confirmed from datasheets, and may affect physical fit:

| Item | Current value | Basis | How to confirm |
|------|--------------|-------|----------------|
| MAX98357A mount hole X position | ±7.53mm | 2mm-from-edge assumption | Open `.brd` in Eagle/KiCad; measure `MOUNTINGHOLE_2.5_PLATED` element coords |
| Pi Zero 2W mount holes | ±29mm / ±11.5mm | 3.5mm-from-edge assumption | Download official Pi mechanical drawing PDF from datasheets.raspberrypi.com |
| Pi Camera v3 mount holes | ±10.5mm / ±10mm | 2mm-from-edge assumption | Same PDF source |

Impact if wrong: standoff/wall bosses will be misaligned. Self-tapping plastic forgives <0.5mm; larger errors prevent thread engagement.

---

## [893ce47] — battery cradle with zip-tie tabs exported as part of body shell

Battery cradle geometry (base plate, end stops, zip-tie tabs with slots) moved from visual-only `encGroup` boxes into `cradleGeos` — merged into the watertight export body. Zip-tie tabs have 3.5×2.5mm slots for 3mm cable ties.

## [d4987ec] — 3MF export: separate manifold parts, open-top body, correct print layout

Two-part 3MF export: body and lid as separate manifold shells. Body inner cavity overshoots top by 1mm to produce clean open-top tray. Lid translated to print-plate position beside body in export file.

## [172958c] — 3D viewer: in-plane PCB dims, click-to-focus, orientation gizmo, layout fixes

PCB dimension annotations drawn in the PCB plane rather than floating. Click on any component to focus camera. Orientation gizmo added to corner. Various panel layout fixes.

## [e24ee83] — CSG cutout walls, tessellation toggle, STL/3MF export, local component images

Wall geometry switched to CSG boolean subtraction for lens/dome/speaker/USB-C holes. Wireframe tessellation overlay toggle. STL and 3MF export buttons. Component images served from local `/static/components/`.

## [eba9d5e] — PCB-art face textures, PIR vertical wall mount, shell opacity slider

Canvas-drawn PCB top-view textures on component faces. PIR and camera mounted vertically on front wall interior. Shell opacity slider to see inside without removing the enclosure.
