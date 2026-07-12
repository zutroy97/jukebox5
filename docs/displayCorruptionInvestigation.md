# JukeboxPanel display corruption investigation — session summary

Branch: `main`.
Status: **reopened.** Display corruption, believed resolved by the TXS0108E
bypass (see "Resolution" below), has recurred — but in a categorically
different form this time (uniform patterns now garble too, not just mixed
ones), while a genuine, unrelated kernel driver bug was found and fixed in
the same session. See "2026-07-11 evening: reopened" at the end for current
state and the next thing to check.

## The symptom

`w3`/`w4` text writes (and the equivalent binary-ioctl writes) to the 7-segment
displays sometimes render garbled characters instead of the requested text.
Keypad reading has always worked correctly throughout.

Key observed characteristics of the corruption:
- **Pattern-dependent.** Uniform patterns (all segments on via `w4 8888`, all
  off via `off`) always render correctly. Mixed patterns (`w4 1234`,
  `w4 4321`) are the ones that garble. This matters: an all-1s or all-0s
  frame can't reveal a bit-alignment, framing, or signal-integrity error,
  since it looks the same regardless of shift/timing/ringing. Only
  non-uniform patterns exercise that.
- **Not simply flaky-random.** In one test run it worked correctly 4 times
  in a row, then failed and *stayed* failed on identical subsequent
  commands. Not a clean one-shot flake.
- **Survives a full power cycle.** Corruption reappeared after the user
  power-cycled the whole Pi, not just reloading the module — rules out any
  accumulated software/kernel state as the cause.
- An LED (`led0`/`led1`) has been observed to spuriously light up during a
  plain `w4` text write that never touched LED state, meaning corruption
  isn't confined to the character-segment bits; it can land in the LED
  bits (28-31) of the same 32-bit word too.

## What's been ruled out this session

1. **The new binary ioctl interface** (branch `binary-panel-interface`,
   parked, not merged): diffed byte-for-byte against the last known-good
   commit and confirmed it changes nothing in the display bit-banging path
   — purely additive. Corruption reproduces identically via the old text
   protocol, so it isn't an ioctl-specific bug.
2. **Bit-bang clock timing.** `bit_delay_us` is a live, root-writable sysfs
   module param now (was a `#define`). Tested from 400us up to 2000us
   (5x slower) — no improvement. Also confirmed via datasheet that
   `udelay()` can only ever make a phase *longer* than requested, never
   shorter, and the MM5450 datasheet only specifies *minimum* high/low
   times (950ns) with no documented maximum — so simple timing-margin
   theories don't hold up under scrutiny anyway.
3. **Scheduler preemption during the ~30ms transaction.** Wrapped
   `update_display()` in `preempt_disable()`/`preempt_enable()` as a test —
   no improvement. (Note: this only rules out *task* preemption, not
   hardware interrupts landing mid-transaction; a `local_irq_disable()`
   test was proposed but never actually run — still open if revisited.)
4. **Power supply brownout.** Measured VDD at the chips while displaying
   `8888` (worst-case current draw, all segments + both LEDs): held at a
   healthy 5.1V, comfortably inside the MM5450's 4.5-11V spec.
5. **Dead/miswired segments.** The all-lit test proved every segment and
   LED is physically connected and drivable — but see the caveat above,
   this doesn't test bit-alignment/timing correctness, only "is anything
   physically disconnected."
6. **Protocol/framing mismatches vs. the real chip.** Retrieved the actual
   MM5450/MM5451 datasheet (Microchip DS20005651A) and the real, working
   Arduino reference source (now committed at
   `docs/ArduinoRefJukeboxPanel/`, previously untracked/not in git
   history). Corrected the driver to match the proven reference exactly
   byte-for-byte:
   - `write_bit()`: removed an extra post-clock-high `udelay()` that the
     reference never had (was roughly tripling transaction length).
   - `update_display()`: frame is 1 start + 32 data + **4** filler bits
     (37 clocks total) — matches the reference exactly. (A datasheet-
     literal reading suggested 3 filler/36 total; that was wrong relative
     to what's actually proven to work, even though the datasheet itself
     doesn't fully explain the discrepancy.)
   - `scan_keypad_raw()`: leaves `DISPLAY_ENABLE` high and the
     data/select lines wherever the last scan step left them afterward —
     matching `getCurrentKeypadValue()` exactly. (Earlier in the session
     this was "fixed" to restore an idle-low state, which seemed
     reasonable but actually diverged from the proven design; reverted.)
   - **Result: rebuilt, reloaded, retested — corruption still occurs
     after all of the above, including after a full power cycle.**
     This means the bug is not a protocol/logic mismatch at all; the
     driver now matches known-good behavior exactly.

## Current leading hypothesis: the TXS0108E level shifter

Per `jukeboxPanelModule/WIRING.md`, a **TXS0108E** (auto-direction-sensing,
8-channel) level shifter sits between the Pi's 3.3V GPIO and the panel's
5V logic. This chip has a well-documented (TI-acknowledged, widely
reported) weakness: it's designed for slow/quasi-bidirectional signals
like I2C, and is known to produce **ringing and false edge detection when
multiple channels switch simultaneously** or when line
capacitance/inductance is nontrivial (even short 6" jumper wires are
called out as enough to cause problems in TI/community reports).

This driver's protocol toggles clock + data3 + data4 (+ matrix_c during
scans) **simultaneously on every single bit** — exactly the stress case
this chip struggles with. It plausibly explains every observed
characteristic: pattern-dependence (more simultaneous transitions = more
chances to glitch), immunity to all the software-timing experiments above
(this is an analog signal-integrity issue, not a logic/timing bug), and
persistence across power cycles (deterministic electrical behavior given
a specific bit pattern, not accumulated state).

### The planned test (in progress, paused for a power-down)

The MM5450 only needs ≥2.2V for a logic HIGH at 5V VDD — the Pi's 3.3V
GPIO clears that easily. Plan: **temporarily bypass the TXS0108E for the
5 Pi→board output lines** (clock, enable, data4, data3, matrix_c —
WIRING.md channels A1-A5/B1-B5) by wiring the Pi GPIO pins directly to
the board's D2/D4/D7/D8/D9 pins, skipping the level shifter for just
those. Leave the 2 board→Pi input lines (keypad rows, channels A6-A7/B6-B7)
going through the level shifter as-is, since those carry 5V toward the
Pi's 3.3V-max inputs and still need protection.

If this fixes it: the long-term fix is replacing the TXS0108E with a
proper unidirectional buffer for the output side (e.g. a 74AHCT541 octal
buffer) rather than leaving a bare 3.3V/5V bypass in place permanently.

**This is where the session paused** — user was about to power off the Pi
to make this wiring change, and will resume testing after.

## Other loose ends (lower priority, not yet done)

- `/DATA ENABLE` (pin 23) continuity check on both MM5450 chips — was
  proposed earlier, user said hardware/wiring looked fine at a glance but
  this specific pin was never verified with a meter. Worth revisiting if
  the level-shifter bypass doesn't fully resolve things.
- `local_irq_disable()` (vs. the already-tried `preempt_disable()`) around
  the transaction — never actually tested. Low priority now given the
  level-shifter hypothesis is much better supported, but still on the
  table if that doesn't pan out.

## Branches / repo state

- `main`: has the keypad-scan-idle-state and frame-length fixes from
  *earlier* in this session, which were later found to diverge from the
  proven Arduino reference and were reverted on `driver_woes`. **`main` is
  currently out of date relative to what's proven correct** — once the
  hardware issue is resolved and `driver_woes` is validated, it should be
  merged back to `main`.
- `driver_woes`: current working branch. Has the `.gitignore` `.DS_Store`
  fix and the Arduino-reference realignment commit.
- `binary-panel-interface`: parked. Built and mechanically exercised
  (all ioctls fired without kernel errors) but not fully validated,
  since the hardware corruption bug was discovered/chased using it and
  then shown to be independent of it. Worth re-testing once the hardware
  issue is fixed, so as not to conflate two problems.
- `docs/ArduinoRefJukeboxPanel/`: the original proven-working Arduino
  sketch (`JukeboxPanel.cpp`/`.h`/`.ino`), now committed as the
  authoritative reference for this protocol — supersedes the
  MM5450/MM5451 datasheet's own framing description where they disagree.

## Resolution

The planned bypass (Pi GPIO wired directly to the board's D2/D4/D7/D8/D9,
skipping the TXS0108E for the 5 output lines — clock, enable, data4, data3,
matrix_c) fixed the display corruption. This confirms the TXS0108E was the
actual root cause of the original symptom, not a protocol/timing/software
issue — consistent with everything in the "ruled out" list above.

### Follow-on: six keypad buttons went silent after the bypass

Immediately after the bypass, buttons `1 3 4 6 7 9` stopped registering
while `0 2 5 8 R P` kept working. This looked alarming (like the
level-shifter problem had just moved to the input side) but turned out to
be unrelated: **`keypad_in0` (GPIO25, level-shifter channel A6/B6) got
physically disconnected during the bypass rewiring itself**, and simply
needed to be reconnected. Worth recording *how* this was diagnosed in
software, without touching the hardware, since the same trick is useful
for any future one-line-stuck-at-X symptom:

`scan_keypad_raw()` packs the two row inputs into one 16-bit word — the low
byte is `keypad_in0` across all 8 scan steps, the high byte is
`keypad_in1`. Decoding the fixed signature table in `raw_to_key()` by byte
showed every *working* key's signature had low byte `0xFF` (never needs
`keypad_in0` to read low), and every *non-working* key's signature needed
`keypad_in0` to drop low at some step. That's the signature of one input
line stuck permanently high, not six independent flaky keys — which
pointed straight at `keypad_in0`/GPIO25 rather than a keypad-wide or
software issue, before any multimeter came out.

Note for next time: `keypad_in0`/`keypad_in1` still route through the
TXS0108E (only the 5 output lines were bypassed) since they're 5V board
signals into 3.3V-max Pi inputs — don't bare-wire-bypass those the way the
outputs were bypassed without a proper divider or unidirectional buffer.

**Status now (superseded by the section below):** display writes and all
keypad buttons confirmed working. `main` is still out of date relative to
`driver_woes` (see above) — worth merging now that both symptoms are
resolved.

## 2026-07-11 evening: reopened

After the above was written and merged to `main`, two new pieces of work
happened in the same session, one a confirmed fix and one an open problem:

### Confirmed fix: kernel driver was silently dropping the newline on every button event

Built `src/panel/jukebox_panel_linux_ascii.py`
(`JukeboxPanelLinuxAsciiModule`) to talk to `/dev/jukebox_panel` directly
from Python using the existing text protocol, and wired it into
`build_panel()` in `main.py` under the `"Raspberry Pi GPIO Linux Driver"`
config name (`[jukeboxPanel1]` in `config.ini`, `device=/dev/jukebox_panel`).
Switching `config.ini`'s `[jukeboxPanel].option` to `jukeboxPanel1` and
running the app end-to-end, the keypad appeared completely dead through
this new module — but a raw `cat /dev/jukebox_panel` showed the kernel
driver *was* seeing every press correctly.

Root cause, in `jukeboxPanelModule/jukebox_panel.c`'s `queue_button_event()`:

```c
char event[6];
int len = scnprintf(event, sizeof(event), "BTN:%c\n", key);
```

`"BTN:%c\n"` is 6 data bytes (`B`,`T`,`N`,`:`,char,`\n`), but `scnprintf`
also needs room for a NUL terminator, so a 6-byte buffer only ever fit 5
data bytes — the trailing `\n` was silently truncated on *every* button
event this driver has ever emitted. Consecutive presses ran together with
no delimiter (`BTN:8BTN:3BTN:7BTN:2`, no separators at all), which any
newline-delimited reader (my new module's `split('\n')`, and in principle
any future consumer) would parse as zero complete lines. This was never
caught before because nothing had strictly required the `\n` boundary
until this module existed — `JukeboxPanelArduinoSerial` never hit it since
it talks to different (correctly-behaved) Arduino firmware over serial,
not this kernel driver.

Fix: `char event[7]`. Rebuilt (`make` in `jukeboxPanelModule/`), reloaded
(`sudo rmmod jukebox_panel && sudo insmod jukebox_panel.ko` — needs to be
run manually, no passwordless sudo on this box). Confirmed via raw `cat`
(now shows proper `BTN:X\n` lines with `cat -A`) and via the new Python
module directly (all 12 keys received correctly by `onButtonPress`). **Not
yet committed** — sitting as a working-tree change in
`jukeboxPanelModule/jukebox_panel.c`, along with the new
`jukebox_panel_linux_ascii.py` and the `main.py`/`build_panel()` wiring.

### Open problem: display corruption is back, and worse than before

Running the full app with the Linux driver active, the panel display
looked corrupted and track selection mostly failed. Isolated the display
part directly (bypassing the app) by sending known patterns straight to
`/dev/jukebox_panel`: **`w4 8888` and `off` now garble too** — not just
mixed patterns like `1234`/`4321`. This is a materially different symptom
from the original investigation above, where uniform patterns were the one
thing that *always* rendered correctly (that was the key evidence pointing
at the TXS0108E's simultaneous-multi-channel-switching weakness at the
time).

Reasoning so far, not yet confirmed:
- Keypad scanning was independently verified perfect in this same session
  (raw `cat` test, all 12 keys, clean signatures). `scan_keypad_raw()`
  drives `enable`, `data4`, `data3`, and `matrix_c` — the same four lines
  `update_display()` uses. It never touches `clock`. That makes `clock`
  (Pi GPIO17 → board D2, one of the 5 lines direct-wire-bypassed around
  the level shifter) the one signal exercised by display writes but not by
  the keypad scan that just proved everything else on that bypass is
  intact. Not yet physically checked.
- No code in `write_bit()`/`update_display()` has changed since displays
  last looked good (only `queue_button_event()`'s buffer size changed,
  which is unrelated). So this looks like a new physical fault introduced
  sometime during the recent hardware handling (the `keypad_in0`
  reconnection, or handling the board again for the module rebuild),
  rather than a logic regression.
- Tested whether repeated writes of the same uniform pattern (`w4 8888`
  sent 5x in a row, no `off` in between) would self-heal, on the theory
  that the MM5450 has no dedicated reset pin and finds frame boundaries by
  watching for a start-bit pattern (both data lines high together) rather
  than a hard frame marker — so a one-time missed/extra clock edge could
  desync the chip's idea of where a frame starts, corrupting even
  legitimately-uniform data until it resyncs. **Result of that test was
  not observed** — session ended (user stepped away from the machine)
  before checking the display after the 5 repeated writes.

### Next steps (pick up here)

1. **First thing to check:** did the 5x-repeated `w4 8888` test (already
   sent, see command run right before session end) come back clean on any
   of the 5 attempts? If yes, this points at intermittent signal
   integrity/resync rather than a hard break, and a software resync
   (holding both data lines low for many clock pulses before a real write)
   is worth adding as a real fix. If no — it never self-heals — that rules
   out resync and points back at a physical fault.
2. **Second:** physically check continuity on the `clock` line (Pi GPIO17
   ↔ board D2), the one line display writes need that the just-verified
   keypad scan doesn't touch.
3. Once display is confirmed good again, retest track selection through
   the full app — the keypad-to-track-selection *logic* itself was already
   confirmed working in this session (`617` successfully matched a
   playlist entry and issued `queue_next` over MQTT via the logs), so that
   part likely doesn't need further debugging once the display is legible
   again.
4. Commit the confirmed newline-buffer fix, the new
   `JukeboxPanelLinuxAsciiModule`, and its `main.py` wiring — these are
   validated independently of the display corruption problem and don't
   need to wait on it.
5. `config.ini`'s `[jukeboxPanel].option` is currently pointed at
   `jukeboxPanel1` (Linux driver) as a local uncommitted change, left that
   way deliberately so the next session can pick up testing immediately.
