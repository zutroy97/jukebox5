from enum import Enum
from abc import abstractmethod, ABC
import logging
from adafruit_ht16k33 import segments

from ..abstract_animator import AbstractAnimator

# The HT16K33 14-segment decimal point is bit 14 of a character's 16-bit
# segment word. The adafruit library's _put() method handles '.' by ORing
# this bit into the PREVIOUS character rather than advancing the cursor —
# we replicate that here so get_char_pattern callers can use the same logic.
DECIMAL_POINT_BIT = 0x4000


class AbstractLED16Animator(AbstractAnimator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    @staticmethod
    def get_char_pattern(char: str) -> int:
        '''Converts a character to a 16-bit segment bitmask for a 14-segment display.

        Decimal points and commas are handled as follows:
          '.'  — returns DECIMAL_POINT_BIT (0x4000). The CALLER is responsible
                 for ORing this into the bitmask of the preceding character rather
                 than placing it in its own display position, matching the behaviour
                 of adafruit_ht16k33 Seg14x4._put().
          ','  — treated identically to '.' since a comma occupies the same lower
                 dot segment on a 14-segment display and there is no distinct glyph.

        Characters outside the printable ASCII range (32-127) are returned as 0
        (blank segment).
        '''
        if char == '.' or char == ',':
            return DECIMAL_POINT_BIT

        if not 32 <= ord(char) <= 127:
            return 0

        character = ord(char) * 2 - 64
        return (segments.CHARS[character] << 8) | segments.CHARS[1 + character]

    @staticmethod
    def string_to_char_mask(s: str) -> list[int]:
        '''Converts a string to a list of 16-bit segment bitmasks.

        Decimal points and commas are folded into the preceding character's bitmask
        (ORed in) and do not consume an extra display position, matching the
        adafruit_ht16k33 Seg14x4 rendering behaviour.

        Characters outside the printable ASCII range (32-127) are represented as 0.
        '''
        masks: list[int] = []
        for ch in s:
            pattern = AbstractLED16Animator.get_char_pattern(ch)
            if pattern == DECIMAL_POINT_BIT and masks:
                # Fold the decimal point into the preceding character.
                masks[-1] |= DECIMAL_POINT_BIT
            else:
                masks.append(pattern)
        return masks

    @abstractmethod
    def Next(self) -> bool:
        '''Returns true if more data is available'''
        return False

    @abstractmethod
    def Start(self) -> None:
        '''Start/Restarts the animation'''
        pass

    @abstractmethod
    def GetSegments(self) -> list[int]:
        '''Returns the segments to be displayed'''
        return []
    