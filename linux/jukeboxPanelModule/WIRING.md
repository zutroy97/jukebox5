# JukeboxPanel wiring (Raspberry Pi, direct-wire + resistor dividers)

The JukeboxPanel board was originally built for a 5V/16MHz Arduino Pro Mini.
Raspberry Pi GPIO runs at 3.3V and is not 5V-tolerant on inputs, so this
originally went through a TXS0108E (8-channel auto-direction-sensing level
shifter) between the Pi and the board. **The TXS0108E has since been
removed entirely** and replaced with two simpler, per-direction solutions:

- The 5 Pi→board output lines (clock, enable, data3, data4, matrix select)
  are **direct-wired**, Pi GPIO straight to the board pin, no shifting
  component at all. The MM5450/MM5451 chips only need ≥2.2V for a logic
  HIGH at 5V VDD, which 3.3V clears comfortably. This was adopted after the
  TXS0108E was identified as the cause of display corruption under this
  driver's simultaneous-multi-line-toggle protocol — see
  `docs/displayCorruptionInvestigation.md` for the full investigation.
  **Known caveat, not yet resolved:** this is a bare 3.3V signal driving
  what may include ordinary 5V CMOS logic elsewhere on the board before
  the signal reaches the MM5450s, which is a marginal voltage threshold in
  principle; current mitigation is added dwell time per bit
  (`bit_delay_us` in `jukebox_panel.c`), not a hardware fix. An HCT-family
  unidirectional buffer (`74HCT541`/`74HCT244`/`74AHCT125`) between the Pi
  and the board remains the more robust fix if corruption ever resurfaces
  — see that doc's "2026-07-12: resolved (for now)" section.
- The 2 board→Pi keypad row input lines (5V board signal into 3.3V-max Pi
  inputs) use a **passive resistor voltage divider** per line — 10kΩ/18kΩ,
  see `docs/keypadInputDividerPoC.md` for why a divider is valid here (the
  board drives both logic levels push-pull, so there's no pull-up to skew
  the ratio) and the derivation of the resistor values. Built, tested, and
  in production use.

These BCM GPIO numbers match the current defaults in `jukebox_panel.c`
(`gpio_clock`, `gpio_enable`, etc.) and are unchanged from the TXS0108E-era
wiring. If you wire to different pins, override them at load time via
`/etc/modprobe.d/jukebox-panel.conf` (e.g. `options jukebox_panel
gpio_clock=5 ...`) rather than editing the source.

## Output lines: direct wire (Pi 3.3V GPIO → board 5V input)

| Signal | Pi BCM GPIO | Pi physical pin | Board / old Arduino pin |
|---|---|---|---|
| Shift clock | GPIO17 | 11 | D2 |
| Display/keypad enable | GPIO27 | 13 | D4 |
| 4-digit display data | GPIO22 | 15 | D7 |
| 3-digit display data | GPIO23 | 16 | D8 |
| Matrix select | GPIO24 | 18 | D9 |

Wire each Pi GPIO pin directly to its board pin — no other components in
the path.

## Input lines: resistor divider (board 5V output → Pi 3.3V-max GPIO)

| Signal | Pi BCM GPIO | Pi physical pin | Board / old Arduino pin |
|---|---|---|---|
| Keypad row input 0 | GPIO25 | 22 | D10 |
| Keypad row input 1 | GPIO5 | 29 | D11 |

One divider per line:

```
board 5V signal ──[R1 = 10kΩ]──┬──> Pi GPIO (25 or 5)
                                 │
                          [R2 = 18kΩ]
                                 │
                                GND (shared with board GND and Pi GND)
```

`Vout = 5V × 18k / (10k + 18k) ≈ 3.21V` — comfortably inside the Pi's 3.3V
logic range. See `docs/keypadInputDividerPoC.md` for the full derivation,
alternative resistor pairs, and the build/validation procedure this was
tested against.

Ground reference for the Pi side: any GND pin on the 40-pin header works
(e.g. physical pin 9, 14, 20, 25, 30, 34, or 39). Tie the divider ground
legs, board GND, and Pi GND all together.

## Validating the wiring

Once wired, with the `jukebox_panel` module loaded (`lsmod | grep jukebox_panel`,
or `/dev/jukebox_panel` exists), test directly with no Python involved:

```sh
# Write to the 3-digit display
echo -e "w3 123\r" > /dev/jukebox_panel

# Write to the 4-digit display
echo -e "w4 4567\r" > /dev/jukebox_panel

# Toggle the LEDs
echo -e "led0 1\r" > /dev/jukebox_panel   # right LED on
echo -e "led0\r"   > /dev/jukebox_panel   # right LED off
echo -e "led1 1\r" > /dev/jukebox_panel   # left LED on
echo -e "led1\r"   > /dev/jukebox_panel   # left LED off

# Blank displays (LEDs untouched)
echo -e "c\r" > /dev/jukebox_panel

# Turn everything off (displays + LEDs)
echo -e "off\r" > /dev/jukebox_panel

# Watch for button presses (Ctrl-C to stop)
cat /dev/jukebox_panel
```

Pressing a button should print a line like `BTN:5`, `BTN:R`, or `BTN:P`.
