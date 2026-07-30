"""Direct I2C driver for the HT16K33 alphanumeric LED driver chip.

Replaces adafruit_ht16k33.segments.Seg14x4 (and the Adafruit-Blinka stack
underneath it) with a small smbus2-based implementation. Covers only the
subset of that API this codebase actually uses -- brightness, fill, show,
set_digit_raw, _put, and i2c_device (for its length) -- so existing callers
work unmodified. The register protocol (oscillator-on, blink/display-on,
brightness, and the 17-byte show() payload: one register-address byte
followed by 16 bytes of display RAM, 2 bytes per character, low byte
first) and the FONT table were ported from the real (MIT-licensed)
Adafruit_CircuitPython_HT16K33 source rather than guessed, so segment
patterns match exactly.
"""
import smbus2

_OSCILLATOR_ON = 0x21
_BLINK_CMD_DISPLAY_ON = 0x81  # blink command | display-on | rate=0 (blink is never used here)
_CMD_BRIGHTNESS = 0xE0
_DECIMAL_POINT_BIT = 0b01000000  # high byte, bit 6 -> bit 14 overall

# char -> 16-bit segment bitmask (bits 0-13 = segments A-N, bit 14 = DP),
# covering ASCII 32-127. Ported from adafruit_ht16k33.segments.CHARS.
FONT = {
    ' ': 0x0000,
    '!': 0x4006,
    '"': 0x0220,
    '#': 0x12ce,
    '$': 0x12ed,
    '%': 0x0c24,
    '&': 0x235d,
    "'": 0x0400,
    '(': 0x2400,
    ')': 0x0900,
    '*': 0x3fc0,
    '+': 0x12c0,
    ',': 0x0800,
    '-': 0x00c0,
    '.': 0x0000,
    '/': 0x0c00,
    '0': 0x0c3f,
    '1': 0x0006,
    '2': 0x00db,
    '3': 0x008f,
    '4': 0x00e6,
    '5': 0x2069,
    '6': 0x00fd,
    '7': 0x0007,
    '8': 0x00ff,
    '9': 0x00ef,
    ':': 0x1200,
    ';': 0x0a00,
    '<': 0x2440,
    '=': 0x00c8,
    '>': 0x0980,
    '?': 0x60a3,
    '@': 0x02bb,
    'A': 0x00f7,
    'B': 0x128f,
    'C': 0x0039,
    'D': 0x120f,
    'E': 0x00f9,
    'F': 0x0071,
    'G': 0x00bd,
    'H': 0x00f6,
    'I': 0x1200,
    'J': 0x001e,
    'K': 0x2470,
    'L': 0x0038,
    'M': 0x0536,
    'N': 0x2136,
    'O': 0x003f,
    'P': 0x00f3,
    'Q': 0x203f,
    'R': 0x20f3,
    'S': 0x00ed,
    'T': 0x1201,
    'U': 0x003e,
    'V': 0x0c30,
    'W': 0x2836,
    'X': 0x2d00,
    'Y': 0x1500,
    'Z': 0x0c09,
    '[': 0x0039,
    '\\': 0x2100,
    ']': 0x000f,
    '^': 0x0c03,
    '_': 0x0008,
    '`': 0x0100,
    'a': 0x1058,
    'b': 0x2078,
    'c': 0x00d8,
    'd': 0x088e,
    'e': 0x0858,
    'f': 0x0071,
    'g': 0x048e,
    'h': 0x1070,
    'i': 0x1000,
    'j': 0x000e,
    'k': 0x3600,
    'l': 0x0030,
    'm': 0x10d4,
    'n': 0x1050,
    'o': 0x00dc,
    'p': 0x0170,
    'q': 0x0486,
    'r': 0x0050,
    's': 0x2088,
    't': 0x0078,
    'u': 0x001c,
    'v': 0x2004,
    'w': 0x2814,
    'x': 0x28c0,
    'y': 0x200c,
    'z': 0x0848,
    '{': 0x0949,
    '|': 0x1200,
    '}': 0x2489,
    '~': 0x0520,
    '\x7f': 0x3fff,
}


class HT16K33Chip:
    """One physical HT16K33 chip: 4 alphanumeric characters, 8 bytes of
    display RAM (2 bytes per character, low byte first)."""

    def __init__(self, bus: smbus2.SMBus, address: int) -> None:
        self._bus = bus
        self._address = address
        self._buffer = bytearray(16)
        self._bus.write_byte(address, _OSCILLATOR_ON)
        self._bus.write_byte(address, _BLINK_CMD_DISPLAY_ON)
        self._brightness = 1.0
        self.brightness = 1.0
        self.show()

    @property
    def brightness(self) -> float:
        return self._brightness

    @brightness.setter
    def brightness(self, value: float) -> None:
        self._brightness = value
        level = round(15 * value) & 0x0F
        self._bus.write_byte(self._address, _CMD_BRIGHTNESS | level)

    def fill(self, on: bool) -> None:
        value = 0xFF if on else 0x00
        for i in range(len(self._buffer)):
            self._buffer[i] = value

    def show(self) -> None:
        # Register address 0x00 followed by all 16 bytes of display RAM, as
        # one contiguous I2C write -- deliberately not smbus2's
        # write_i2c_block_data/write_block_data helpers, which add SMBus
        # framing (e.g. a leading byte-count byte) the HT16K33 doesn't
        # expect; i2c_rdwr sends exactly the bytes given, matching what
        # busio.I2C.writeto() does at the wire level.
        msg = smbus2.i2c_msg.write(self._address, bytes([0x00]) + bytes(self._buffer))
        self._bus.i2c_rdwr(msg)

    def set_digit_raw(self, local_index: int, bitmask: int) -> None:
        bitmask &= 0xFFFF
        self._buffer[local_index * 2] = bitmask & 0xFF
        self._buffer[local_index * 2 + 1] = (bitmask >> 8) & 0xFF

    def put(self, char: str, local_index: int) -> None:
        """Put a single character at the given position, deferring show()
        to the caller (matches adafruit_ht16k33 Seg14x4._put())."""
        if char == '.':
            self._buffer[local_index * 2 + 1] |= _DECIMAL_POINT_BIT
            return
        mask = FONT.get(char, 0x0000)
        self._buffer[local_index * 2] = mask & 0xFF
        self._buffer[local_index * 2 + 1] = (mask >> 8) & 0xFF


class Seg14x4Native:
    """Drop-in replacement for adafruit_ht16k33.segments.Seg14x4, covering
    only the methods this codebase calls: brightness, fill, show,
    set_digit_raw, _put, auto_write, and i2c_device (for its length, to
    compute display width)."""

    def __init__(self, address, bus_number: int = 1, bus: smbus2.SMBus = None) -> None:
        addrs = address if isinstance(address, (tuple, list)) else (address,)
        self._bus = bus if bus is not None else smbus2.SMBus(bus_number)
        self.i2c_device = [HT16K33Chip(self._bus, addr) for addr in addrs]
        self._chars = 4 * len(self.i2c_device)
        # Matches adafruit_ht16k33.HT16K33's auto_write: when True (the
        # default), fill()/set_digit_raw() push their change to the
        # hardware immediately; _put() never does regardless (see below),
        # since led16_display.py's write() relies on _put() being
        # buffer-only and calling flush()/show() itself once per frame.
        self.auto_write = True

    @property
    def brightness(self) -> float:
        return self.i2c_device[0].brightness

    @brightness.setter
    def brightness(self, value: float) -> None:
        for chip in self.i2c_device:
            chip.brightness = value

    def fill(self, on) -> None:
        for chip in self.i2c_device:
            chip.fill(bool(on))
        if self.auto_write:
            self.show()

    def show(self) -> None:
        for chip in self.i2c_device:
            chip.show()

    def set_digit_raw(self, index: int, bitmask: int) -> None:
        chip_index, local_index = divmod(index, 4)
        self.i2c_device[chip_index].set_digit_raw(local_index, bitmask)
        if self.auto_write:
            self.show()

    def _put(self, char: str, index: int) -> None:
        if not 0 <= index < self._chars:
            return
        if not 32 <= ord(char) <= 127:
            return
        chip_index, local_index = divmod(index, 4)
        self.i2c_device[chip_index].put(char, local_index)
