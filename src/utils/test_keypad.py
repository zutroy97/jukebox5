#!/usr/bin/env python3
"""Standalone keypad test: prints each settled key press read from a
jukebox panel driver, with nothing else (no displays, no MQTT, no
coordinator) in the loop -- so the keypad-detection path (kernel driver ->
Python driver -> decoded character) can be exercised and timed in
isolation, e.g. to tell a hardware/wiring fault apart from an application
bug, or to check for sluggish/dropped presses.

Usage: test_keypad.py [--driver binary|ascii|serial] [--device PATH]
                       [--port /dev/ttyUSB0] [--baud 115200] [--raw]

--raw (binary driver only) bypasses signature-to-character decoding and
prints every raw 2-byte scan signature the kernel driver reports,
including ones that don't match any entry in the character lookup table --
those are normally silently dropped (see
JukeboxPanelLinuxBinaryModule._SIGNATURES's docstring: "release-transients,
bounce artifacts"). Useful for telling a marginal/noisy electrical contact
(settles on an unrecognized signature -- shows up here as UNKNOWN, invisible
in normal mode) apart from a real decode-table bug (settles on the *wrong*
recognized signature -- shows up here as the wrong key).
"""
import argparse
import os
import struct
import sys
import time
from pathlib import Path

# So `panel.*` is importable regardless of CWD/how this script is invoked --
# mirrors src/ being on sys.path when running `python3 main.py` from there.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panel.jukebox_panel_linux_ascii import JukeboxPanelLinuxAsciiModule
from panel.jukebox_panel_linux_binary import JukeboxPanelLinuxBinaryModule, _SIGNATURES
from panel.panel_input_base import JukeboxPanelArduinoSerial

_DEFAULT_DEVICE = {
    "binary": "/dev/jukebox_panel_bin",
    "ascii": "/dev/jukebox_panel",
}


def build_driver(args, onButtonPress):
    if args.driver == "serial":
        from serial import Serial
        port = Serial(port=args.port, baudrate=args.baud, timeout=None)
        return JukeboxPanelArduinoSerial(port=port, onButtonPress=onButtonPress)

    device = args.device or _DEFAULT_DEVICE[args.driver]
    driver_cls = JukeboxPanelLinuxBinaryModule if args.driver == "binary" else JukeboxPanelLinuxAsciiModule
    return driver_cls(device=device, onButtonPress=onButtonPress)


def run_raw(device_path: str):
    """Reads 2-byte scan signatures straight off the kernel device, with no
    driver/decoding in between -- every settled signature the kernel
    reports is printed, whether or not it's in _SIGNATURES."""
    fd = os.open(device_path, os.O_RDWR)
    buf = b""
    last_at = None
    try:
        while True:
            chunk = os.read(fd, 64)
            if not chunk:
                continue
            buf += chunk
            n_complete = len(buf) // 2
            for i in range(n_complete):
                (raw,) = struct.unpack_from("=H", buf, i * 2)
                key = _SIGNATURES.get(raw)
                now = time.monotonic()
                since_last = f"  (+{now - last_at:.3f}s)" if last_at is not None else ""
                last_at = now
                decoded = f"-> {key!r}" if key is not None else "-> UNKNOWN (would be dropped)"
                print(f"{time.strftime('%H:%M:%S')}  raw=0x{raw:04x}  {decoded}{since_last}", flush=True)
            buf = buf[n_complete * 2:]
    except KeyboardInterrupt:
        print("done", flush=True)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--driver", choices=["binary", "ascii", "serial"], default="binary",
        help="which panel driver to test (default: binary, matches jukeboxPanel2 in config.ini)",
    )
    parser.add_argument(
        "--device", default=None,
        help="device path for the binary/ascii Linux drivers "
             "(default: /dev/jukebox_panel_bin or /dev/jukebox_panel, per --driver)",
    )
    parser.add_argument("--port", default="/dev/ttyUSB0", help="serial port for the Arduino serial driver")
    parser.add_argument("--baud", type=int, default=115200, help="baud rate for the Arduino serial driver")
    parser.add_argument(
        "--raw", action="store_true",
        help="bypass decoding and print raw signatures instead (binary driver only)",
    )
    args = parser.parse_args()

    if args.raw:
        if args.driver != "binary":
            parser.error("--raw is only supported with --driver binary")
        device = args.device or _DEFAULT_DEVICE["binary"]
        print(f"Listening for raw signatures on {device} ... (Ctrl-C to quit)", flush=True)
        run_raw(device)
        return

    last_press_at = None

    def onButtonPress(key: str):
        nonlocal last_press_at
        now = time.monotonic()
        since_last = f"  (+{now - last_press_at:.3f}s)" if last_press_at is not None else ""
        last_press_at = now
        print(f"{time.strftime('%H:%M:%S')}  key={key!r}{since_last}", flush=True)

    print(f"Listening for key presses via the {args.driver!r} driver ... (Ctrl-C to quit)", flush=True)
    build_driver(args, onButtonPress)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("done", flush=True)


if __name__ == "__main__":
    main()
