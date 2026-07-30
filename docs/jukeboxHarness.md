## Wiring harness diagrams for the Jukebox panel.

### DIP10 Adaptor Pinout
```

Wires+--5--4--3--2--1--+
=====|                 |
=====|                 |
=====|                 |
     +--6--7--8--9--1--+
                    0
```

### 13 pin Jukebox Harness
```
+-+ Wiring Harness out the Right Side
| 1|==== VDD1
| 2|==== GND
| 3|==== N/A
| 4|==== N/A
| 5|==== Keypad 0
| 6|==== Keypad 1
| 7|==== 4 Digit Display Data
| 8|==== N/C
| 9|==== 3 Digit Display Data
|10|==== Matrix Select
|11|==== Clock
|12|==== Display Enable
|13|==== VDD2
```

### Pin Mappings and Descriptions

The "Pi GPIO (BCM)" / "Pi Header Pin #" columns are the current Raspberry Pi
side of the harness, via the TXS0108E level shifter described in
[`linux/jukeboxPanelModule/WIRING.md`](../linux/jukeboxPanelModule/WIRING.md) and
matching the `gpio_*` module params in `linux/jukeboxPanelModule/jukebox_panel.c`
(pin numbers are physical/board pin numbers on the 40-pin GPIO header, not
BCM or wiringPi numbering).

| Example Arduino Sketch PIN | 13 Pin # | 10 Pin # | Signal | Direction | Purpose | Pi GPIO (BCM) | Pi Header Pin # |
|-|----------|----------|--------|-----------|---------|---------------|------------------|
|  | 1 | 6 | VDD1 | - | +5v power (Board 1) | - | External 5V supply (level shifter VCCB) — not the Pi header, see `WIRING.md` |
| | 2 | 5 | GND | - | Ground | - | Any GND pin (e.g. 9, 14, 20, 25, 30, 34, or 39) |
|  | 3 | X | N/C | - | Not connected | - | - |
|  | 4 | X | N/C | - | Not connected | - | - |
| 10 | 5 | 8 | `KEY_IN_0` | In | Keypad matrix sense line 0 | GPIO25 | 22 |
| 11 | 6 | 7 | `KEY_IN_1` | In | Keypad matrix sense line 1 | GPIO5 | 29 |
| 7 | 7 | 4 | `DISPLAY_4` (4-digit / `Z8`) | Out | Serial data for the 4-character display | GPIO22 | 15 |
|  | 8 | X | N/C | - | Not connected | - | - |
| 8 | 9 | 3 | `DISPLAY_3` (3-digit / `Z3`) | Out | Serial data for the 3-character display | GPIO23 | 16 |
| 9 | 10 | 2 | `MATRIX_SELECT` | Out | High-order select line, shared/multiplexed with keypad scanning | GPIO24 | 18 |
| 2 | 11 | 1 | `CLOCK` | Out | Shared bit clock for the display shift registers | GPIO17 | 11 |
| 4 | 12 | 10 | `DISPLAY_ENABLE` | Out | Gates the shift-register output latch / display driver | GPIO27 | 13 |
|  | 13 | 9 | VDD2 | - | +5v power (Board 2) | - | External 5V supply (level shifter VCCB) — not the Pi header, see `WIRING.md` |

The level shifter's Pi-side (VCCA) power/ground and its `OE` pin also come
off the 40-pin header but aren't part of the 13-pin harness itself:

| Level shifter pin | Pi GPIO (BCM) | Pi Header Pin # | Purpose |
|---|---|---|---|
| VCCA | - | 1 or 17 (3.3V) | Level shifter Pi-side supply |
| OE | - | 1 or 17 (3.3V) | Tied to VCCA to enable level shifting |
| GNDA | - | Any GND pin (shared with GNDB) | Level shifter Pi-side ground |


## JukeboxPanel Protocol

> The two display data pins and the matrix select pin are time-multiplexed: they drive the displays most of the time, but during a keypad scan they're repurposed as a 3-bit address bus.

---

### Display Output Protocol

Each display is driven by an MM5450 or MM5451 LED display driver chip (National Semiconductor / Microchip), which accepts a synchronous serial stream clocked in on the rising edge of `CLOCK`, with bit timing controlled by explicit delays rather than a fixed baud rate.

Per the MM5450/MM5451 datasheet, a full display update is a **36-clock-pulse transaction** — 1 start bit plus exactly 35 data bits, with no separate load/latch signal (the chip auto-latches after the 36th clock):

1. **Enable phase** — raise `DISPLAY_ENABLE`.
2. **Start condition** — drive both data lines HIGH simultaneously, pulse `CLOCK` low→high, then hold for 400µs. A logical "1" start bit, as the very first bit of the frame.
3. **Data phase** — shift out 35 bits total, one per line, LSB first: the first 32 come from the packed display word, the remaining 3 are zero filler. For each bit:
   - Place the bit value for `DISPLAY_4` and `DISPLAY_3` on their respective lines
   - Pulse `CLOCK` low, wait 400µs, then `CLOCK` high

   Each of the two 32-bit words encodes one display's full segment pattern (and, for the 4-digit display, two auxiliary LED states packed into its top bits). Bit 1 (the first bit after the start bit) lands on the chip's Output 1, and so on in order — so the 32-bit word occupies Outputs 1-32, with Outputs 33-35 always off (zero filler).
4. **Commit** — drop `DISPLAY_ENABLE` low. The chip itself already latched the new pattern automatically at clock 36; dropping enable here matches the driver's idle level between writes.

Each character position's value is a 7-bit segment mask (bits for segments a–g), and up to four such masks are packed together (7 bits each) into the 32-bit word shifted per display, most-significant character first (the source string is reversed before encoding).

---

### Keypad Input Protocol

The keypad is not wired as simple discrete buttons — it's read as a **scanned matrix**, and it reuses the display's data/select lines as a 3-bit address bus while `DISPLAY_ENABLE` is held low (disconnecting the display drivers so they don't fight the scan).

For each of **8 scan steps** (address `0`–`7`):

1. Drive the 3-bit address (LSB on `DISPLAY_4`, next bit on `DISPLAY_3`, MSB on `MATRIX_SELECT`) — this presumably feeds a demultiplexer that energizes one row/column combination of the physical key matrix at a time.
2. Sample both `KEY_IN_1` and `KEY_IN_0`.
3. Accumulate:
   - `KEY_IN_1`'s reading for this step → bit `i` of a 16-bit result
   - `KEY_IN_0`'s reading for this step → bit `i+8`

After all 8 steps, the accumulated 16-bit value is a unique **signature** depending on which keypad contacts are shorted by a pressed key (each key shorts a distinct combination of matrix lines). This raw signature is matched against a fixed lookup table to resolve it to a character:

| Character | Signature (hex) |
|---|---|
| `0` | `0xDDFF` |
| `1` | `0xFDDF` |
| `2` | `0xFCFF` |
| `3` | `0xFDF7` |
| `4` | `0xFDFC` |
| `5` | `0xEDFF` |
| `6` | `0xFDEF` |
| `7` | `0xFD3F` |
| `8` | `0xF5FF` |
| `9` | `0xFDFB` |
| `P` | `0x7DFF` |
| `R` | `0xBDFF` |
| *(none)* | any other value — including the all-open "nothing pressed" state |

---

### Debounce / Reporting Algorithm

Raw keypad signatures are noisy during the mechanical bounce of a press/release, so a debounce layer sits on top of the raw scan:

- The raw decoded key is sampled continuously (once per main loop iteration).
- Whenever the sampled key changes from the previous sample, a timer resets.
- Only if the same key value has been stable for **more than 50ms** is it considered a genuine, settled press.
- Each settled press is reported **exactly once** — it won't re-report the same key repeatedly while held; a new report only fires after the key changes to something else and a new key stabilizes.
- Confirmed key events are emitted as an asynchronous text notification (`BTN:<char>`) over the serial link.