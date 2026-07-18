#!/usr/bin/env python3
"""Segment-by-segment hardware test for the 14-segment HT16K33 displays at
I2C addresses 0x70/0x71 (the 8-character "label" line -- see
docs/SPECIFICATION.md).

Lights each of the display's 14 segments (plus the decimal point) one at a
time, in lockstep across every character position, so a bad solder joint or
dead segment is easy to spot by eye. The bit-to-segment mapping below was
reverse-engineered from adafruit_ht16k33.segments.CHARS by checking known
glyphs ('8' = 0xFF = A-G2, '-' = 0xC0 = G1+G2, '_' = 0x08 = D, '1' = 0x06 =
B+C, 'H' = 0xF6, '0' = 0xC3F which adds K+L as the zero-slash, 'X' = 0x2D00
= the four diagonals H/K/L/N).

Usage: test_14seg.py [--addr 0x70,0x71] [--delay 0.6] [--brightness 0.5] [--mode all]
"""
import argparse
import time

from busio import I2C
import board
from adafruit_ht16k33 import segments

# bit -> (short label, human description), per the 14-segment + decimal
# point layout.
SEGMENTS = [
    (0, "A", "top"),
    (1, "B", "upper right"),
    (2, "C", "lower right"),
    (3, "D", "bottom"),
    (4, "E", "lower left"),
    (5, "F", "upper left"),
    (6, "G1", "middle left"),
    (7, "G2", "middle right"),
    (8, "H", "upper left diagonal"),
    (9, "J", "upper vertical"),
    (10, "K", "upper right diagonal"),
    (11, "L", "lower left diagonal"),
    (12, "M", "lower vertical"),
    (13, "N", "lower right diagonal"),
    (14, "DP", "decimal point"),
]

ALL_SEGMENTS_ON = 0x7FFF


def parse_addrs(raw: str):
    return tuple(int(a, 0) for a in raw.split(","))


def set_all_chars(display: segments.Seg14x4, value: int):
    """Write the same raw 15-bit segment pattern to every character position."""
    lo = value & 0xFF
    hi = (value >> 8) & 0xFF
    for i in range(display._chars):
        display._set_buffer(display._adjusted_index(i * 2), lo)
        display._set_buffer(display._adjusted_index(i * 2 + 1), hi)
    display.show()


def run_lamp_test(display: segments.Seg14x4, hold_s: float):
    print("lamp test: all segments on", flush=True)
    set_all_chars(display, ALL_SEGMENTS_ON)
    time.sleep(hold_s)


def run_sweep(display: segments.Seg14x4, hold_s: float):
    for bit, label, desc in SEGMENTS:
        print(f"segment {bit:2d}  {label:<3s}  {desc}", flush=True)
        set_all_chars(display, 1 << bit)
        time.sleep(hold_s)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--addr", default="0x70,0x71",
        help="comma-separated I2C addresses of the HT16K33 chips to test (default: 0x70,0x71)",
    )
    parser.add_argument(
        "--delay", type=float, default=0.6,
        help="seconds to hold each segment on (default: 0.6)",
    )
    parser.add_argument(
        "--brightness", type=float, default=0.5,
        help="display brightness 0.0-1.0 (default: 0.5)",
    )
    parser.add_argument(
        "--mode", choices=["all", "lamp", "sweep"], default="all",
        help="'lamp' turns every segment on and holds, 'sweep' cycles through "
             "each segment individually, 'all' (default) runs both in order",
    )
    args = parser.parse_args()

    addrs = parse_addrs(args.addr)
    i2c = I2C(board.SCL, board.SDA)
    display = segments.Seg14x4(i2c, address=addrs)
    display.brightness = args.brightness

    try:
        if args.mode in ("all", "lamp"):
            run_lamp_test(display, args.delay)
        if args.mode in ("all", "sweep"):
            run_sweep(display, args.delay)
    except KeyboardInterrupt:
        pass
    finally:
        display.fill(0)
        print("done", flush=True)


if __name__ == "__main__":
    main()
