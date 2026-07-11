# JukeboxPanel wiring (Raspberry Pi + TXS0108E level shifter)

The JukeboxPanel board was originally built for a 5V/16MHz Arduino Pro Mini.
Raspberry Pi GPIO runs at 3.3V and is not 5V-tolerant on inputs, so a
TXS0108E (or equivalent 8-channel auto-direction-sensing level shifter) sits
between the Pi and the board. Every signal here is unidirectional in this
protocol (the Pi always drives clock/enable/data3/data4/matrix-c; the board
always drives the two keypad row lines back), so the TXS0108E's auto-sensing
works cleanly -- no DIR pins to configure.

These BCM GPIO numbers match the current defaults in `jukebox_panel.c`
(`gpio_clock`, `gpio_enable`, etc.). If you wire to different pins, override
them at load time via `/etc/modprobe.d/jukebox-panel.conf` (e.g.
`options jukebox_panel gpio_clock=5 ...`) rather than editing the source.

## Level shifter power/ground

| Module pin | Connect to |
|---|---|
| VCCA | Pi 3.3V (physical pin 1 or 17) |
| GNDA | Pi GND |
| VCCB | 5V supply for the JukeboxPanel board's logic |
| GNDB | Same ground as GNDA (tie GNDA and GNDB together -- common ground) |
| OE   | Tie to VCCA (3.3V) to enable level shifting (some breakouts already pull this high internally -- check yours) |

## Signal channels (A-side = Pi/3.3V, B-side = board/5V)

| Signal | Pi BCM GPIO | Pi physical pin | Level shifter channel | Board / old Arduino pin |
|---|---|---|---|---|
| Shift clock | GPIO17 | 11 | A1 <-> B1 | D2 |
| Display/keypad enable | GPIO27 | 13 | A2 <-> B2 | D4 |
| 4-digit display data | GPIO22 | 15 | A3 <-> B3 | D7 |
| 3-digit display data | GPIO23 | 16 | A4 <-> B4 | D8 |
| Keypad matrix column-select bit 2 | GPIO24 | 18 | A5 <-> B5 | D12 |
| Keypad row input 0 | GPIO25 | 22 | A6 <-> B6 | D13 |
| Keypad row input 1 | GPIO5 | 29 | A7 <-> B7 | D14 (A0) |

Channel 8 (A8/B8) is unused -- fine to leave floating on both sides.

Ground reference for the Pi side: any GND pin on the 40-pin header works
(e.g. physical pin 9, 14, 20, 25, 30, 34, or 39).

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
