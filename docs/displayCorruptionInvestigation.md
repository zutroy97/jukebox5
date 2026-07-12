# JukeboxPanel display corruption investigation — session summary

Branch: `driver_woes` (commits `2da2d44`, `82c8563` as of this writing).
Status: **resolved.** The TXS0108E level-shifter bypass (see below) fixed the
display corruption. It also caused a follow-on symptom — six keypad buttons
silently not registering — which was a wiring mistake made during the bypass
itself, not a new instance of the level-shifter problem. See "Resolution"
section at the end.

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

**Status now:** display writes and all keypad buttons confirmed working.
`main` is still out of date relative to `driver_woes` (see above) — worth
merging now that both symptoms are resolved.
