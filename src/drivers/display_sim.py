import os
import sys
import time

# Segment characters (characters to use for simulation)
#_____
#|\|/|
#--+--
#|/|\|
#-----.
#
# Segment Mapping. 1 = G1 2 = G2 . = DP
#
#AAAAA
#FHJKB
# 1 2
#ELMNC
#DDDDD.


class TerminalAlphanumeric14:
    def __init__(self):
        # The display has 4 alphanumeric digits.
        # Each digit holds a 16-bit register tracking lit segments.
        self.buffer = [0] * 4

        # Core ANSI Color Codes requested
        self.LIT = "\033[1;31m"    # Bold Red
        self.UNLIT = "\033[0;90m"  # Dark Gray
        self.RESET = "\033[0m"     # Reset colors

        # Segment bit mapping for this display
        # A1/A2 are aliases for the same shared top segment.
        # D1/D2 are aliases for the same shared bottom segment.
        # A1 A2 B C E F G1 G2 H D2 J K L D1 DP
        SEG = {
            'A': 1 << 0,
            'A1': 1 << 0,
            'A2': 1 << 0,
            'B': 1 << 2,
            'C': 1 << 3,
            'E': 1 << 4,
            'F': 1 << 5,
            'G1': 1 << 6,
            'G2': 1 << 7,
            'H': 1 << 8,
            'J': 1 << 10,
            'K': 1 << 11,
            'L': 1 << 12,
            'D': 1 << 13,
            'D1': 1 << 13,
            'D2': 1 << 13,
            'DP': 1 << 14,
        }
        self.FONT = {
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
        }

    def write_digit_raw(self, digit_idx, bitmask):
        """Emulates void writeDigitRaw(uint8_t n, uint16_t bitmask)"""
        if 0 <= digit_idx < 4:
            self.buffer[digit_idx] = bitmask & 0xFFFF

    def write_digit_ascii(self, digit_idx, char, dot=False):
        """Emulates void writeDigitAscii(uint8_t n, uint8_t ascii, boolean dot)"""
        char = char.upper()
        mask = self.FONT.get(char, 0x0000)
        if dot:
            mask |= 0x4000  # Bit 14 represents the Decimal Point (DP)
        self.write_digit_raw(digit_idx, mask)

    def print_text(self, text):
        """Helper to quickly fill out all 4 characters on the display matrix."""
        # Clean string to account for inline trailing dots
        display_chars = []
        dots = [False] * 4
        
        idx = 0
        for char in text:
            if idx >= 4: break
            if char == '.' and idx > 0:
                dots[idx-1] = True
            else:
                display_chars.append(char)
                idx += 1

        while len(display_chars) < 4:
            display_chars.append(' ')

        for i in range(4):
            self.write_digit_ascii(i, display_chars[i], dots[i])

    def _seg(self, mask, bit):
        """Returns the appropriate color string if a specific segment bit is high."""
        return f"{self.LIT}█{self.RESET}" if (mask & (1 << bit)) else f"{self.UNLIT}░{self.RESET}"

    def render(self):
        """Draws the terminal graphic of all 4 modules side-by-side using the buffer."""
        lines = ["" for _ in range(5)]
        
        for mask in self.buffer:
            # Row 0: Top Horizontal segment (shared A)
            a = self._seg(mask, 0)
            lines[0] += f" {a}{a}{a} {a}{a}{a}    "

            # Row 1: Upper Diagonal/Vertical elements (F, H, J, B)
            f = self._seg(mask, 5)
            h = self._seg(mask, 8)
            j = self._seg(mask, 10)
            b = self._seg(mask, 2)
            lines[1] += f"{f}  {h} {j}  {b}   "

            # Row 2: Middle Cross elements (G1, G2)
            g1 = self._seg(mask, 6)
            g2 = self._seg(mask, 7)
            lines[2] += f" {g1}{g1}{g1} {g2}{g2}{g2}    "

            # Row 3: Lower Diagonal/Vertical elements (E, K, L, C)
            e = self._seg(mask, 4)
            k = self._seg(mask, 11)
            l = self._seg(mask, 12)
            c = self._seg(mask, 3)
            lines[3] += f"{e}  {k} {l}  {c}   "

            # Row 4: Bottom Horizontal segment (shared D) & Dot
            d = self._seg(mask, 13)
            dp = self._seg(mask, 14)
            lines[4] += f" {d}{d}{d} {d}{d}{d}  {dp} "

        # Clear screen console trick to avoid terminal flooding
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n" + "\n".join(lines) + "\n")


# --- Test Demonstration Loop ---
if __name__ == "__main__":
    display = TerminalAlphanumeric14()

    # Test: Show all segments lit to understand the layout
    print("Test 1: All segments on...")
    for digit in range(4):
        display.write_digit_raw(digit, 0x7FFF)  # All 15 bits on
    display.render()
    time.sleep(2)

    # Test: Individual segment bits
    print("\nTest 2: Individual bits (0-14)...")
    for bit in range(15):
        print(f"BIT: {bit}")
        for digit in range(4):
            display.write_digit_raw(digit, 1 << bit)
        display.render()
        time.sleep(0.5)

    # Demonstration 1: Text Strings
    print("\nDemonstration 1: Text Strings")
    demo_phrases = ["HELO", "ADAF", "14.SE", "G.LED", "COOL"]
    print("Starting Text Emulation Demo...")
    time.sleep(1)

    for word in demo_phrases:
        display.print_text(word)
        display.render()
        time.sleep(1.5)

    # Demonstration 2: Direct Protocol Bitmask (Lighting all segments raw)
    print("\nDemonstration 2: Testing Raw Bitmask Entry (Lighting every segment one by one)...")
    time.sleep(1)
    
    raw_mask = 0x0000
    for bit in range(15):
        raw_mask |= (1 << bit)
        for digit in range(4):
            display.write_digit_raw(digit, raw_mask)
        display.render()
        time.sleep(0.3)
