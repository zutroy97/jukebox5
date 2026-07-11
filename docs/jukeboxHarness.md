# Wiring harness diagrams for the Jukebox panel.

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
| 1|==== +5v
| 2|==== Gnd
| 3|==== N/A
| 4|==== N/A
| 5|==== Keypad B
| 6|==== Keypad A
| 7|==== Display Z8 Data In
| 8|==== N/C
| 9|==== Display Z3 Data In
|10|==== Keypad Matrix C
|11|==== Display Clock
|12|==== Display Enable
|13|==== Keypad Out C
```

| 13 pin # | 10 pin # | Description | Direction |
|----------|----------|-------------|----|
| 1 | 6 | Vdd / +5v | - |
| 2 | 5 | Gnd | - |
| 3 | X | N/C | - |
| 4 | X | N/C | - |
| 5 | 8 | Keypad B | INPUT |
| 6 | 7 | Keypad A | INPUT |
| 7 | 4 | 4 Digit Display (Z8) | OUTPUT |
| 8 | X | N/C | - |
| 9 | 3 | 3 Digit Display (Z3) | OUTPUT |
| 10 | 2 | Matrix Select | OUTPUT |
| 11 | 1 | Clock | OUTPUT |
| 12 | 10 | Display Enable | OUTPUT |
| 13 | 9 | Keypad Out C | OUTPUT |


# JukeboxPanel Protocol

## Physical Interface

Seven signal lines connect the microcontroller to the panel:

| Signal | Direction | Purpose |
|---|---|---|
| `CLOCK` | Out | Shared bit clock for the display shift registers |
| `DISPLAY_ENABLE` | Out | Gates the shift-register output latch / display driver |
| `DATA_A` (4-digit line) | Out | Serial data for the 4-character display |
| `DATA_B` (3-digit line) | Out | Serial data for the 3-character display |
| `MATRIX_SELECT` | Out | High-order select line, shared/multiplexed with keypad scanning |
| `KEY_IN_1` | In | Keypad matrix sense line 1 |
| `KEY_IN_2` | In | Keypad matrix sense line 2 |

> The two display data pins and the matrix select pin are time-multiplexed: they drive the displays most of the time, but during a keypad scan they're repurposed as a 3-bit address bus.

---

## Display Output Protocol

The displays are driven by shift registers that accept a synchronous serial stream, clocked in on the rising edge of `CLOCK`, with bit timing controlled by explicit delays rather than a fixed baud rate.

A full display update is a **36-clock-pulse transaction**:

1. **Enable phase** — raise `DISPLAY_ENABLE`.
2. **Start condition** — drive both data lines HIGH simultaneously, pulse `CLOCK` low→high, then hold for 400µs. This distinct "both lines high" pattern acts as a frame marker distinguishing a new transaction.
3. **Data phase** — shift out 32 bits, one per line, LSB first. For each bit:
   - Place the bit value for `DATA_A` and `DATA_B` on their respective lines
   - Pulse `CLOCK` low, wait 400µs, then `CLOCK` high

   Each of the two 32-bit words encodes one display's full segment pattern (and, for the 4-digit display, two auxiliary LED states packed into its top bits).
4. **Padding phase** — send 4 additional clock pulses with both data lines held LOW. The downstream shift-register/latch hardware requires a full 36-bit frame (32 data + 4 filler) before it will latch and light the new pattern — sending only 32 leaves the display unchanged.
5. **Commit** — drop `DISPLAY_ENABLE` low, which latches/displays the newly shifted-in values.

Each character position's value is a 7-bit segment mask (bits for segments a–g), and up to four such masks are packed together (7 bits each) into the 32-bit word shifted per display, most-significant character first (the source string is reversed before encoding).

---

## Keypad Input Protocol

The keypad is not wired as simple discrete buttons — it's read as a **scanned matrix**, and it reuses the display's data/select lines as a 3-bit address bus while `DISPLAY_ENABLE` is held low (disconnecting the display drivers so they don't fight the scan).

For each of **8 scan steps** (address `0`–`7`):

1. Drive the 3-bit address (LSB on `DATA_A`, next bit on `DATA_B`, MSB on `MATRIX_SELECT`) — this presumably feeds a demultiplexer that energizes one row/column combination of the physical key matrix at a time.
2. Sample both `KEY_IN_1` and `KEY_IN_2`.
3. Accumulate:
   - `KEY_IN_1`'s reading for this step → bit `i` of a 16-bit result
   - `KEY_IN_2`'s reading for this step → bit `i+8`

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

## Debounce / Reporting Algorithm

Raw keypad signatures are noisy during the mechanical bounce of a press/release, so a debounce layer sits on top of the raw scan:

- The raw decoded key is sampled continuously (once per main loop iteration).
- Whenever the sampled key changes from the previous sample, a timer resets.
- Only if the same key value has been stable for **more than 50ms** is it considered a genuine, settled press.
- Each settled press is reported **exactly once** — it won't re-report the same key repeatedly while held; a new report only fires after the key changes to something else and a new key stabilizes.
- Confirmed key events are emitted as an asynchronous text notification (`BTN:<char>`) over the serial link.
MDEOF

<br/>

# JukeboxPanel Protocol

## Physical Interface

Seven signal lines connect the microcontroller to the panel:

| Signal | Direction | Purpose |
|---|---|---|
| `CLOCK` | Out | Shared bit clock for the display shift registers |
| `DISPLAY_ENABLE` | Out | Gates the shift-register output latch / display driver |
| `DATA_A` (4-digit line) | Out | Serial data for the 4-character display |
| `DATA_B` (3-digit line) | Out | Serial data for the 3-character display |
| `MATRIX_SELECT` | Out | High-order select line, shared/multiplexed with keypad scanning |
| `KEY_IN_1` | In | Keypad matrix sense line 1 |
| `KEY_IN_2` | In | Keypad matrix sense line 2 |

> The two display data pins and the matrix select pin are time-multiplexed: they drive the displays most of the time, but during a keypad scan they're repurposed as a 3-bit address bus.

---

## Display Output Protocol

The displays are driven by shift registers that accept a synchronous serial stream, clocked in on the rising edge of `CLOCK`, with bit timing controlled by explicit delays rather than a fixed baud rate.

A full display update is a **36-clock-pulse transaction**:

1. **Enable phase** — raise `DISPLAY_ENABLE`.
2. **Start condition** — drive both data lines HIGH simultaneously, pulse `CLOCK` low→high, then hold for 400µs. This distinct "both lines high" pattern acts as a frame marker distinguishing a new transaction.
3. **Data phase** — shift out 32 bits, one per line, LSB first. For each bit:
   - Place the bit value for `DATA_A` and `DATA_B` on their respective lines
   - Pulse `CLOCK` low, wait 400µs, then `CLOCK` high

   Each of the two 32-bit words encodes one display's full segment pattern (and, for the 4-digit display, two auxiliary LED states packed into its top bits).
4. **Padding phase** — send 4 additional clock pulses with both data lines held LOW. The downstream shift-register/latch hardware requires a full 36-bit frame (32 data + 4 filler) before it will latch and light the new pattern — sending only 32 leaves the display unchanged.
5. **Commit** — drop `DISPLAY_ENABLE` low, which latches/displays the newly shifted-in values.

Each character position's value is a 7-bit segment mask (bits for segments a–g), and up to four such masks are packed together (7 bits each) into the 32-bit word shifted per display, most-significant character first (the source string is reversed before encoding).

---

## Keypad Input Protocol

The keypad is not wired as simple discrete buttons — it's read as a **scanned matrix**, and it reuses the display's data/select lines as a 3-bit address bus while `DISPLAY_ENABLE` is held low (disconnecting the display drivers so they don't fight the scan).

For each of **8 scan steps** (address `0`–`7`):

1. Drive the 3-bit address (LSB on `DATA_A`, next bit on `DATA_B`, MSB on `MATRIX_SELECT`) — this presumably feeds a demultiplexer that energizes one row/column combination of the physical key matrix at a time.
2. Sample both `KEY_IN_1` and `KEY_IN_2`.
3. Accumulate:
   - `KEY_IN_1`'s reading for this step → bit `i` of a 16-bit result
   - `KEY_IN_2`'s reading for this step → bit `i+8`

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

## Debounce / Reporting Algorithm

Raw keypad signatures are noisy during the mechanical bounce of a press/release, so a debounce layer sits on top of the raw scan:

- The raw decoded key is sampled continuously (once per main loop iteration).
- Whenever the sampled key changes from the previous sample, a timer resets.
- Only if the same key value has been stable for **more than 50ms** is it considered a genuine, settled press.
- Each settled press is reported **exactly once** — it won't re-report the same key repeatedly while held; a new report only fires after the key changes to something else and a new key stabilizes.
- Confirmed key events are emitted as an asynchronous text notification (`BTN:<char>`) over the serial link.