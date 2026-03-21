# DeerHunter — Assembly Guide

Complete step-by-step instructions for building a DeerHunter trail camera kit.

**Tools required:** Small Phillips screwdriver, flush-cut snips (for zip ties), soldering iron + solder, wire stripper, multimeter (optional but recommended).

**Time:** ~2 hours for a first build.

---

## Bill of Materials

| # | Component | Qty | Notes |
|---|-----------|-----|-------|
| 1 | Raspberry Pi Zero 2W | 1 | Headers pre-soldered or solder yourself |
| 2 | Pi Camera Module v3 NoIR | 1 | Includes CSI ribbon cable |
| 3 | HC-SR501 PIR Sensor | 1 | — |
| 4 | MAX98357A I2S Amplifier | 1 | Adafruit breakout board |
| 5 | Visaton K 50 WP 8Ω (Art. 2915) | 1 | IP65, weatherproof, 50mm, 2W/3W |
| 6 | 18650 LiPo Battery Pack (3.7V ~5Ah) | 1 | Protected cells with PCB |
| 7 | TP4056 LiPo Charger Module | 1 | USB-C input version preferred |
| 8 | 6V 1W Solar Panel | 1 | With bare leads |
| 9 | 3D Printed Enclosure | 1 | PETG recommended, see `/enclosure` page |
| 10 | Double-sided velcro pads 20×20mm | 3 | For battery retention |
| 11 | 3mm cable ties 100mm (zip ties) | 2 | UV-stabilised nylon |
| 12 | M2.5 × 5mm standoffs (brass) | 4 | Pi Zero mounting |
| 13 | M2.5 screws | 4 | Pi Zero to standoffs |
| 14 | M2 screws | 4 | Camera + PIR to front wall bosses |
| 18 | M3 × 12mm screws (self-tapping) | 4 | Lid to corner boss pads |
| 19 | M4 × 12mm screws (self-tapping) | 4 | Speaker to right wall bosses |
| 15 | Jumper wire (female-female, 20cm) | ~10 | GPIO connections |
| 16 | 22 AWG hookup wire (red/black) | ~30cm each | Power rails |
| 17 | MicroSD card (16GB+, Class 10) | 1 | For Pi OS |

---

## Step 1 — Flash the MicroSD Card

1. Download **Raspberry Pi OS Lite (64-bit)** from raspberrypi.com/software.
2. Flash it to the MicroSD card using Raspberry Pi Imager.
3. In Imager's advanced settings (gear icon), configure before flashing:
   - Set **hostname** (e.g. `deerhunter`)
   - Enable **SSH**
   - Set **WiFi SSID and password**
   - Set **username/password**
4. Eject and set the card aside — you'll insert it into the Pi in Step 4.

---

## Step 2 — Print the Enclosure

1. Print the enclosure body and lid in **PETG** (or ASA for outdoor use).
   - 3 perimeters, 20% infill, 0.2mm layer height.
   - The battery cradle, TP4056 rails, and all standoff bosses are part of the body — no separate parts.
2. After printing, clear any stringing from the CSI lens hole, PIR dome hole, speaker hole, and USB-C slot on the right wall using a hobby knife.
3. Test-fit the lens barrel cutout (front wall, left): it should pass a 12mm diameter cylinder.

---

## Step 3 — Install Brass Standoffs (Pi Zero)

The enclosure floor has four 2.5mm boss holes for the Pi's M2.5 mounting holes.

1. Press-fit or lightly thread four **M2.5 × 5mm brass standoffs** into the floor bosses.
   - Bosses are positioned at ±29mm (X) and ±11.5mm (Z) from the Pi centre mark on the floor.
2. If standoffs don't press in, run an M2.5 tap through the holes first.

---

## Step 4 — Mount the Raspberry Pi Zero 2W

1. Insert the **MicroSD card** into the Pi's card slot (top-left edge of the board).
2. Set the Pi onto the four standoffs, component side up.
   - The USB/HDMI edge faces the front wall; the GPIO header faces the rear.
3. Fasten with four **M2.5 screws**. Snug — do not overtighten on the plastic bosses.

---

## Step 5 — Mount the Camera Module (Front Wall)

The camera mounts vertically on the **interior face of the front wall**, lens pointing outward through the circular cutout.

1. Feed the **CSI ribbon cable** through the front wall lens cutout from outside, leaving slack inside the enclosure.
2. Align the camera PCB against the front wall interior:
   - The lens should sit centred in the circular hole.
   - The two M2 boss holes on the PCB align with the printed bosses at ±10.5mm from the lens centre horizontally.
3. Fasten with two **M2 screws**.
4. Connect the **CSI ribbon cable** to the Pi Zero's CSI connector:
   - Lift the locking tab on the Pi's CSI connector.
   - Insert the ribbon with the **metal contacts facing toward the board** (away from the latch side).
   - Press the latch down to lock.

---

## Step 6 — Mount the PIR Sensor (Front Wall)

The HC-SR501 mounts vertically on the **interior face of the front wall**, Fresnel dome pointing out through the circular cutout to the right of the camera.

1. Remove the Fresnel dome (twists off) and set aside.
2. Align the PIR PCB against the front wall interior, dome hole centred on the cutout.
   - M2 bosses are at ±14mm from the PIR centre horizontally.
3. Reattach the Fresnel dome from the outside — it should clip through the wall cutout.
4. Fasten the PCB with two **M2 screws** from inside.
5. Wire the PIR's 3-pin header:
   | PIR pin | Connects to |
   |---------|-------------|
   | VCC (+) | Pi GPIO pin 2 (5V) |
   | GND (−) | Pi GPIO pin 6 (GND) |
   | OUT     | Pi GPIO pin 11 (GPIO 17) |

---

## Step 7 — Mount the MAX98357A Amplifier

The amp mounts flat on the **enclosure floor**, left side, using two M2.5 standoffs.

1. Press-fit two **M2.5 × 5mm standoffs** into the amp cradle bosses on the left side of the floor.
2. Set the MAX98357A onto the standoffs (component side up, speaker terminal toward back wall) and fasten with two **M2.5 screws**.
3. Wire the I2S connections to the Pi GPIO header:
   | MAX98357A pin | Pi GPIO |
   |--------------|---------|
   | VIN          | Pin 4 (5V) |
   | GND          | Pin 9 (GND) |
   | BCLK         | Pin 12 (GPIO 18) |
   | LRC          | Pin 35 (GPIO 19) |
   | DIN          | Pin 40 (GPIO 21) |

---

## Step 8 — Mount the Speaker (Right Wall)

The **Visaton K 50 WP** (50mm, IP65) mounts on the **interior face of the right wall**, cone facing outward through the Ø45.5mm circular cutout.

1. Feed the speaker leads through the right wall grille hole from outside.
2. Position the speaker body against the right wall interior, cone centred on the hole.
3. Fasten with four **M4 × 12mm self-tapping screws** through the four boss holes arranged on a **□31.5mm square pattern** (holes at ±15.75mm in both Y and Z from the speaker centre).
4. Connect speaker leads to the MAX98357A:
   | Speaker | MAX98357A |
   |---------|-----------|
   | + lead  | SPKP (+) terminal |
   | − lead  | SPKM (−) terminal |
   - Use the green screw terminal on the amp board — insert lead, tighten screw.

---

## Step 9 — Install the TP4056 Charger

The TP4056 slides into a friction cradle on the **rear right of the enclosure floor**, USB-C port aligned with the slot in the right wall.

1. Orient the board so the **USB-C port faces the right wall slot**.
2. Slide the TP4056 into the cradle rails (front/rear stops, left/right rails).
   - The USB-C port should protrude slightly into the right wall slot opening.
3. No screws needed — the cradle friction-holds the board.

---

## Step 10 — Prepare and Install the Battery Pack

**Velcro (primary retention — allows tool-free removal for charging):**

1. Cut or peel three **20×20mm double-sided velcro pads**.
2. Press the **hook side** of each pad firmly onto the three positions on the battery cradle base plate (evenly spaced along the battery length).
3. Peel the backing from the **loop side** of each pad and press the battery pack down firmly onto them, centred in the cradle.

**Zip ties (secondary retention — recommended for outdoor/vibration use):**

4. Thread one **3mm × 100mm cable tie** down through the front-left tab slot, under the battery, and up through the front-right tab slot. Cinch and trim the tail flush.
5. Repeat with a second tie through the rear-left and rear-right tab slots.

---

## Step 11 — Wire the Power Rails

1. **Battery → TP4056:**
   - Connect battery pack **red lead** → TP4056 **B+** pad.
   - Connect battery pack **black lead** → TP4056 **B−** pad.

2. **TP4056 → Pi (5V rail):**
   - Solder a red wire to TP4056 **OUT+** pad → Pi GPIO **pin 2 (5V)**.
   - Solder a black wire to TP4056 **OUT−** pad → Pi GPIO **pin 6 (GND)**.
   > ⚠️ Double-check polarity before connecting. Reversed power will damage the Pi.

3. **Solar Panel → TP4056:**
   - Connect solar panel **+ lead** → TP4056 **IN+** (same pads as USB-C, accessible via header).
   - Connect solar panel **− lead** → TP4056 **IN−**.
   - Route the solar cable through the rear wall or lid cable channel.

---

## Step 12 — Software Setup

1. Power the Pi by connecting a USB-C cable to the TP4056's USB-C port (or via the battery once wired).
2. SSH into the Pi: `ssh <username>@deerhunter.local`
3. Clone the repo and run the install script:
   ```bash
   git clone https://github.com/youruser/DeerHunter.git
   cd DeerHunter
   sudo bash install.sh
   ```
   This installs all dependencies, downloads the YOLOv8n TFLite model, and sets up the systemd service.

4. Edit `config/rules.yaml` to set your **ntfy.sh topic**, notification preferences, and detection thresholds:
   ```bash
   nano config/rules.yaml
   ```

---

## Step 13 — Test Before Closing

With the lid off:

1. **Motion test:** Walk in front of the PIR sensor. The activity LED on the Pi should blink and the terminal should log a detection.
2. **Camera test:** `libcamera-still -o test.jpg` — verify image saves to storage.
3. **Audio test:** `aplay sounds/predator_call.wav` — verify sound from speaker.
4. **Notification test:** Trigger a motion event and confirm an ntfy push arrives on your phone.
5. **Charging test:** Connect solar panel in sunlight — the TP4056 red CHG LED should illuminate.
6. **Web dashboard:** Open `http://deerhunter.local:8080` in a browser and verify the Events and Status pages load.

---

## Step 14 — Close and Deploy

1. Route all wires clear of the lid seating surface.
2. Set the lid onto the enclosure body — the four corner boss pads (12×12mm blocks integrated into the wall corners) align with the Ø3.4mm clearance holes in the lid.
3. Fasten the lid with four **M3 × 12mm self-tapping screws** through the corner clearance holes into the boss pad pilots.
4. Mount the enclosure on a post or tree bracket, angled to cover the area you want to monitor.
5. Orient the solar panel toward the south (northern hemisphere) at roughly the same angle as your latitude.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Pi won't boot | Bad SD card or power | Re-flash SD; check 5V rail with multimeter |
| No camera image | CSI ribbon not locked | Re-seat ribbon, verify metal contacts face board |
| PIR not triggering | Wiring or sensitivity too low | Check GPIO 17; adjust PIR sensitivity pot |
| No audio | I2S wiring error | Verify BCLK/LRC/DIN pins against table in Step 7 |
| No notifications | ntfy topic not set | Check `config/rules.yaml` ntfy topic |
| Battery not charging | Solar polarity reversed | Verify + / − at TP4056 IN pads |
