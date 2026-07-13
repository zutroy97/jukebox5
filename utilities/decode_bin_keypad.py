#!/usr/bin/env python3
"""Live-decodes raw keypad signatures from /dev/jukebox_panel_bin.

jukebox_panel_bin.c deliberately reports raw 16-bit scan signatures rather
than decoded characters (see jukeboxPanelModule/jukebox_panel_bin_protocol.h)
-- translating a signature is the caller's job. This is that translation,
useful for watching what the panel actually reports key by key.

Usage: decode_bin_keypad.py [duration_seconds] [device_path]
"""
import os
import select
import struct
import sys
import time

DEFAULT_DEVICE = "/dev/jukebox_panel_bin"

# Matches src/panel/jukebox_panel_linux_binary.py's remapped table: digit
# labels 0<=>5, 1<=>6, 2<=>7, 3<=>8, 4<=>9 (R/P unchanged) relative to
# jukeboxPanelModule/jukebox_panel.c's raw_to_key().
SIGNATURES = {
    0x7dff: 'P',
    0xfddf: '6',
    0xfcff: '7',
    0xfdf7: '8',
    0xfdfc: '9',
    0xedff: '0',
    0xfdef: '1',
    0xfd3f: '2',
    0xf5ff: '3',
    0xfdfb: '4',
    0xddff: '5',
    0xbdff: 'R',
}


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    device = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DEVICE

    fd = os.open(device, os.O_RDWR)
    print(f"reading {device} for {duration:.0f}s, press buttons now...", flush=True)
    end = time.time() + duration
    try:
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.5)
            if not r:
                continue
            chunk = os.read(fd, 64)
            for i in range(len(chunk) // 2):
                (raw,) = struct.unpack_from("=H", chunk, i * 2)
                key = SIGNATURES.get(raw, '?')
                print(f"0x{raw:04x}  ->  {key}", flush=True)
    finally:
        os.close(fd)
    print("done", flush=True)


if __name__ == '__main__':
    main()
