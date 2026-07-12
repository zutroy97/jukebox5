# Proof of concept: resistor-divider replacement for the keypad-input TXS0108E channels

Status: **proposed, not yet built or tested.**

## Goal

Remove the TXS0108E entirely by replacing its last two active channels
(A6/B6 = `keypad_in0`/GPIO25, A7/B7 = `keypad_in1`/GPIO5) with a passive
resistor divider each. The 5 output lines (clock/enable/data3/data4/
matrix_c) already bypass the shifter with a direct wire as of the display
corruption fix — see `docs/displayCorruptionInvestigation.md`. This PoC
covers the 2 remaining lines, which are the opposite direction (board 5V
→ Pi 3.3V) and can't use a direct wire.

## Why a divider is valid here

Confirmed from `docs/ArduinoRefJukeboxPanel/JukeboxPanel.cpp:20-21`:
`_outputPin1`/`_outputPin2` (the two row-sense lines) are configured
`INPUT`, not `INPUT_PULLUP`. The board actively drives both logic levels
itself (push-pull), rather than relying on a pulled-up line that a switch
grounds. That matters because a resistive divider only degrades cleanly
when both ends of the swing are actively driven — an external pull-up on
the board side would interact with the divider's own resistance and skew
the ratio. Since that's not the case here, a plain 2-resistor divider per
line is a valid substitute for the level shifter on these two channels.

A divider only steps a voltage *down*, which is why this approach is
input-only — it's not an option for the 5 Pi→board output lines (already
solved separately via direct wire).

## Circuit (one per line, two required)

```
board 5V signal ──[R1]──┬──> Pi GPIO (25 or 5)
                         │
                        [R2]
                         │
                        GND (shared with board GND and Pi GND)
```

`Vout = 5V × R2 / (R1 + R2)`. Target: comfortably inside the Pi's 3.3V
logic range (don't run right up against the 3.3V rail continuously —
treat that as the ceiling, not the target) while keeping current draw
low enough not to load the board's original 5V logic drivers.

## Resistor combinations

| R1 | R2 | Vout (5V in) | Idle current draw | Notes |
|---|---|---|---|---|
| 1kΩ | 1.8kΩ | 3.21V | 1.79 mA | Good margin, low parts cost, fast settle |
| 1kΩ | 2kΩ | 3.33V | 1.67 mA | Common "I2C-style" ratio; least margin below 3.3V — usable but the tightest of these options |
| 2kΩ | 3kΩ | 3.00V | 1.00 mA | Best margin, still low resistance |
| 4.7kΩ | 8.2kΩ | 3.18V | 0.39 mA | Common E12 values, lower current |
| **10kΩ** | **18kΩ** | **3.21V** | **0.18 mA** | **Recommended default** — same ratio as the 1k/1.8k option at ~10x lower current draw, kindest to the board's original driver ICs |

All of these settle in well under 1µs against the Pi GPIO's few-pF input
capacitance — irrelevant next to the driver's existing 5µs keypad settle
delay (`KEYPAD_SETTLE_US` in `jukebox_panel.c`), so timing is not a
factor in picking a combination. Pick based on parts on hand; the 10k/18k
pair is the recommendation if starting from scratch, with 1k/1.8k as the
fallback if only smaller values are available.

## Bill of materials

- 4x resistors (2 per line) — see table above for the chosen pair
- Breadboard or perfboard for the PoC; no other active parts required

## Build / test procedure

1. **Before wiring anything**, probe `keypad_in0` and `keypad_in1` at the
   board side (upstream of any divider) with a meter: confirm each reads
   close to 0V idle and close to 5V when a key on that row is held. This
   confirms the push-pull assumption above before committing resistor
   values — skipping this was exactly how the loose-connection bug went
   unnoticed during the recent output-bypass rewiring.
2. Build one divider per line on a breadboard first (don't solder yet).
   Tie both dividers' ground legs to the shared Pi/board ground already
   in use.
3. Wire divider outputs to GPIO25 and GPIO5 in place of the current
   TXS0108E A6/A7 connections. Leave the TXS0108E itself in place but
   disconnect only these two channels, so it can be reconnected as a
   fallback without re-wiring from scratch if the PoC doesn't pan out.
4. Load `jukebox_panel` (no code changes needed — this is purely a
   signal-conditioning swap, the driver just reads GPIO25/GPIO5 as
   before) and confirm all 12 keys (`0-9`, `R`, `P`) register via
   `cat /dev/jukebox_panel`, per `jukeboxPanelModule/WIRING.md`'s
   validation steps.
5. Measure actual Vout at each Pi GPIO pin under both idle and
   key-held states with a meter, to confirm it matches the calculated
   value for the chosen resistor pair (catches a wrong-value or
   miswired resistor before it becomes an intermittent-read mystery).
6. If confirmed working and stable, remove the TXS0108E entirely and
   update `WIRING.md` to describe the divider in place of the level
   shifter for these two channels.

## Open question carried over from the corruption investigation

The `/DATA ENABLE` (pin 23) continuity check on both MM5450 chips was
never completed (see `docs/displayCorruptionInvestigation.md`, "Other
loose ends"). Unrelated to this PoC, but worth doing while the board is
already open for this rewiring.
