import os
import struct
import threading
from typing import Optional

from panel.panel_input_base import JukeboxPanelInputBase, JukeboxPanelOutputBase

# Mirrors jukeboxPanelModule/jukebox_panel_bin_protocol.h's struct jbp_bin_cmd
# exactly: cmd(1) + target(1) + pad(2) + value(4) = 8 bytes.
_CMD_FORMAT = "=BBxxI"

JBP_CMD_SET_INT = 1
JBP_CMD_SET_RAW = 2
JBP_CMD_SET_LED = 3

JBP_TARGET_3DIGIT = 0
JBP_TARGET_4DIGIT = 1

JBP_LED_RIGHT = 0  # led0
JBP_LED_LEFT = 1   # led1

# Based on jukeboxPanelModule/jukebox_panel.c's raw_to_key() table, with the
# digit labels remapped 0<=>5, 1<=>6, 2<=>7, 3<=>8, 4<=>9 (R/P unchanged) --
# a deliberate relabeling, not a bug fix; jukebox_panel.c's own table is
# intentionally left as-is. The kernel driver reports raw signatures rather
# than decoding them (see jukebox_panel_bin_protocol.h) -- this is where
# that translation happens. Any signature not in this table
# (release-transients, bounce artifacts) is silently dropped, matching
# raw_to_key()'s '_' default.
_SIGNATURES = {
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

# Mirrors jukeboxPanelModule/jukebox_panel.c's jukebox_characters[] table
# verbatim (index 0-9 = '0'-'9', 10-35 = 'a'-'z').
_JUKEBOX_CHARACTERS = (
    119, 65, 59, 107, 77, 110, 126, 67, 127, 111,   # 0-9
    95, 124, 54, 121, 62, 30, 111, 92, 20, 113,     # a-j
    93, 52, 82, 88, 120, 31, 79, 24, 110, 60,       # k-t
    117, 112, 37, 93, 109, 59,                      # u-z
)


def _character_map(c: str) -> int:
    """Mirrors get_character_map() in jukebox_panel.c exactly."""
    if c == ' ':
        return 0
    if '0' <= c <= '9':
        return _JUKEBOX_CHARACTERS[ord(c) - ord('0')]
    if 'a' <= c <= 'z':
        return _JUKEBOX_CHARACTERS[ord(c) - ord('a') + 10]
    if 'A' <= c <= 'Z':
        return _JUKEBOX_CHARACTERS[ord(c) - ord('A') + 10]
    if c == '-':
        return 8
    return 32  # unmapped -> underscore, matches get_character_map()'s fallback


_DIGIT_BITS = 7
_DIGIT_COUNT = 4
_DIGIT_BITS_MASK = (1 << (_DIGIT_BITS * _DIGIT_COUNT)) - 1  # bits 0-27; bits 28-31 are LED-only on display4


class _RevealState:
    """Tracks in-progress segment-reveal animation for one display's digit
    bits (bits 0-27 of its 32-bit raw word -- LED bits, if any, are OR'd in
    separately by the caller at send time). Digit positions whose target
    segments already match what's shown are left untouched (no animation,
    no flicker); positions that are changing are blanked immediately and
    then reveal their target segments one bit at a time, in bit order, one
    segment per tick -- so a digit needing fewer lit segments (e.g. '1')
    finishes sooner than one needing more (e.g. '8')."""

    def __init__(self) -> None:
        self._current = 0
        self._pending: list[list[int]] = [[] for _ in range(_DIGIT_COUNT)]

    def sync(self, digit_bits: int) -> None:
        """Set the current state directly, with no animation -- for
        non-animated writes, so a later animated write diffs against
        what's actually on the hardware rather than stale tracked state."""
        self._current = digit_bits & _DIGIT_BITS_MASK
        self._pending = [[] for _ in range(_DIGIT_COUNT)]

    def set_target(self, digit_bits: int) -> None:
        digit_bits &= _DIGIT_BITS_MASK
        for i in range(_DIGIT_COUNT):
            shift = i * _DIGIT_BITS
            mask = ((1 << _DIGIT_BITS) - 1) << shift
            target = digit_bits & mask
            if target == (self._current & mask):
                self._pending[i] = []
                continue
            self._current &= ~mask
            self._pending[i] = [b for b in range(_DIGIT_BITS) if digit_bits & (1 << (shift + b))]

    def is_settled(self) -> bool:
        return not any(self._pending)

    def tick(self) -> Optional[int]:
        """Advances every still-animating digit by one segment. Returns the
        new digit-bits word to write, or None if nothing changed this
        tick (already fully settled)."""
        if self.is_settled():
            return None
        changed = False
        for i in range(_DIGIT_COUNT):
            if self._pending[i]:
                bit = self._pending[i].pop(0)
                self._current |= 1 << (i * _DIGIT_BITS + bit)
                changed = True
        return self._current if changed else None


def _pack_text(text: str) -> int:
    """Mirrors pack_display_text() in jukebox_panel.c exactly (minus the LED
    bits, which the caller ORs in separately since this driver has no
    server-side LED state to consult -- see JukeboxPanelLinuxBinaryModule's
    _write_raw). Packs up to 4 characters MSB-first-per-char after
    reversing, so the segment word's bit layout matches the kernel driver's
    JBP_CMD_SET_RAW exactly regardless of whether the text came from here or
    from C."""
    display = 0
    length = len(text)
    for i in range(4):
        if i >= length:
            break
        src_index = length - 1 - i
        display = (display << 7) | _character_map(text[src_index])
    return display


class JukeboxPanelLinuxBinaryModule(JukeboxPanelInputBase, JukeboxPanelOutputBase):
    """Talks to the jukebox_panel_bin kernel module over /dev/jukebox_panel_bin
    using its fixed-size binary command protocol (see
    jukeboxPanelModule/jukebox_panel_bin_protocol.h) -- a separate,
    independently-loadable alternative to jukebox_panel.c's line-based text
    protocol that JukeboxPanelLinuxAsciiModule speaks; only one of the two
    kernel modules is ever loaded at a time.

    Display writes for arbitrary text (WriteToThreeDigitDisplay /
    WriteToFourDigitDisplay) compute the raw 32-bit segment word in Python
    (_pack_text, mirroring jukebox_panel.c's pack_display_text()) and send
    it via JBP_CMD_SET_RAW, since the kernel protocol only understands
    integers and raw segment words, not arbitrary characters.
    WriteNumberTo{Three,Four}DigitDisplay use JBP_CMD_SET_INT directly.

    By default those writes animate: changed digits blank immediately and
    then relight their target segments one at a time (see _RevealState),
    driven by a dedicated background thread (_reveal_loop) at
    reveal_tick_s per segment. Pass animated=False for writes where timing
    must stay exact or that repeat too fast to animate sensibly (live
    keypad echo, a blink sequence) -- see panel_input_base.py's
    JukeboxPanelOutputBase for the parameter's contract across drivers.

    Keypad reads: the kernel driver reports raw 16-bit signatures rather
    than decoded characters by design -- decoding happens here via
    _SIGNATURES.
    """

    READ_CHUNK = 64

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "device" not in kwargs:
            raise TypeError("Missing required keyword argument: 'device'")
        self._device_path = kwargs['device']
        self._fd = os.open(self._device_path, os.O_RDWR)

        # The kernel driver derives its own LED state from whatever bits a
        # JBP_CMD_SET_RAW write carries (see jukebox_panel_bin.c's
        # apply_raw()), rather than preserving prior state the way
        # JBP_CMD_SET_INT's pack_int_display() does. So a text write to the
        # 4-digit display must OR in the current LED bits itself, or it
        # would silently turn the LEDs off as a side effect -- these two
        # fields are what pack_display_text() reads led0_state/led1_state
        # for in the C driver.
        self._led0_state = False
        self._led1_state = False

        # Segment-reveal animation (see _RevealState): one background
        # thread drives both displays' in-progress reveals at a fixed tick
        # rate, woken immediately whenever a new animated write arrives.
        self._reveal_tick_s = kwargs.get('reveal_tick_s', 0.1)
        self._reveal_lock = threading.Lock()
        self._reveal_state = {
            JBP_TARGET_3DIGIT: _RevealState(),
            JBP_TARGET_4DIGIT: _RevealState(),
        }
        self._reveal_wake = threading.Event()

        self._inputBuffer = b''
        # IsRunning must be set before either background thread starts --
        # both read it immediately, and starting a thread before its
        # dependencies exist is exactly the race that has bitten this
        # codebase before (see main.py's coordinator_holder).
        self.IsRunning: bool = True

        self._threadRevealLoop = threading.Thread(target=self._reveal_loop, daemon=True)
        self._threadRevealLoop.start()
        self._threadReadLoop = threading.Thread(target=self._read_loop, daemon=True)
        self._threadReadLoop.start()

    def close(self):
        self.IsRunning = False
        self._reveal_wake.set()
        os.close(self._fd)

    # --- JukeboxPanelOutputBase ---

    def WriteToThreeDigitDisplay(self, message: str, animated: bool = True):
        self._write_raw(JBP_TARGET_3DIGIT, _pack_text(message), animated)

    # WriteNumberTo{Three,Four}DigitDisplay go straight through JBP_CMD_SET_INT
    # (below) rather than _write_raw, so they don't sync the reveal
    # animator's tracked state and can't animate. Not currently called
    # anywhere in this app (WriteToXDigitDisplay with a pre-formatted
    # string is used instead) -- worth revisiting if that changes.
    def WriteNumberToThreeDigitDisplay(self, num: int):
        self._send(JBP_CMD_SET_INT, JBP_TARGET_3DIGIT, num)

    def ClearThreeDigitDisplay(self):
        self.WriteToThreeDigitDisplay('   ')

    def WriteToFourDigitDisplay(self, message: str, animated: bool = True):
        self._write_raw(JBP_TARGET_4DIGIT, _pack_text(message), animated)

    def WriteNumberToFourDigitDisplay(self, num: int):
        self._send(JBP_CMD_SET_INT, JBP_TARGET_4DIGIT, num)

    def ClearFourDigitDisplay(self):
        self.WriteToFourDigitDisplay('    ')

    def LeftLedSet(self, value: bool):
        self._led1_state = value
        self._send(JBP_CMD_SET_LED, JBP_LED_LEFT, 1 if value else 0)

    def RightLedSet(self, value: bool):
        self._led0_state = value
        self._send(JBP_CMD_SET_LED, JBP_LED_RIGHT, 1 if value else 0)

    def Off(self):
        self._led0_state = False
        self._led1_state = False
        self._sync_reveal_state(JBP_TARGET_3DIGIT, 0)
        self._sync_reveal_state(JBP_TARGET_4DIGIT, 0)
        self._send(JBP_CMD_SET_RAW, JBP_TARGET_3DIGIT, 0)
        self._send(JBP_CMD_SET_RAW, JBP_TARGET_4DIGIT, 0)

    def Clear(self):
        """Blanks both digit displays; LEDs untouched -- mirrors
        apply_clear()'s 0xE0000000 mask by re-sending the current LED bits
        alongside blank segments. Instant, not animated -- "clear" should
        read as immediate, not as a reveal running in reverse."""
        self._sync_reveal_state(JBP_TARGET_3DIGIT, 0)
        self._sync_reveal_state(JBP_TARGET_4DIGIT, 0)
        self._send(JBP_CMD_SET_RAW, JBP_TARGET_3DIGIT, 0)
        self._send(JBP_CMD_SET_RAW, JBP_TARGET_4DIGIT, self._led_bits())

    # --- internals ---

    def _led_bits(self) -> int:
        bits = 0
        if self._led0_state:
            bits |= 0x80000000
        if self._led1_state:
            bits |= 0x60000000
        return bits

    def _write_raw(self, target: int, segments: int, animated: bool = True):
        if target == JBP_TARGET_4DIGIT:
            segments |= self._led_bits()
        segments &= 0xFFFFFFFF

        if not animated:
            self._sync_reveal_state(target, segments)
            self._send(JBP_CMD_SET_RAW, target, segments)
            return

        with self._reveal_lock:
            self._reveal_state[target].set_target(segments)
        self._reveal_wake.set()

    def _sync_reveal_state(self, target: int, segments: int) -> None:
        """Tell the reveal animator this target's digit bits were just set
        directly (no animation), so a later animated write diffs against
        what's actually on the hardware instead of stale tracked state."""
        with self._reveal_lock:
            self._reveal_state[target].sync(segments)

    def _reveal_loop(self):
        while self.IsRunning:
            self._reveal_wake.wait(timeout=self._reveal_tick_s)
            self._reveal_wake.clear()
            if not self.IsRunning:
                return

            with self._reveal_lock:
                updates = []
                for target, state in self._reveal_state.items():
                    digit_bits = state.tick()
                    if digit_bits is None:
                        continue
                    raw = digit_bits
                    if target == JBP_TARGET_4DIGIT:
                        raw |= self._led_bits()
                    updates.append((target, raw & 0xFFFFFFFF))

            for target, raw in updates:
                self._send(JBP_CMD_SET_RAW, target, raw)

    def _send(self, cmd: int, target: int, value: int):
        os.write(self._fd, struct.pack(_CMD_FORMAT, cmd, target, value))

    def _read_loop(self):
        while self.IsRunning:
            try:
                chunk = os.read(self._fd, self.READ_CHUNK)
            except OSError:
                if not self.IsRunning:
                    return
                raise

            if not chunk:
                continue

            self._inputBuffer += chunk
            # Keypad signatures are 2-byte (__u16) records; only consume
            # whole ones and keep any trailing odd byte for the next read.
            n_complete = len(self._inputBuffer) // 2
            for i in range(n_complete):
                (raw,) = struct.unpack_from("=H", self._inputBuffer, i * 2)
                key = _SIGNATURES.get(raw)
                if key is not None:
                    self._buttonPressReceived(key)
            self._inputBuffer = self._inputBuffer[n_complete * 2:]
