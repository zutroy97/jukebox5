import logging
from . import abstract_line_display

from .ht16k33_native import Seg14x4Native


class led16_display(abstract_line_display.AbstractSingleLineDisplay):

    def __init__(self, **kwargs) -> None:
        self._logger = logging.getLogger(__class__.__name__)
        addr = kwargs.get('addr', (0x72, 0x73, 0x74))
        self._display = Seg14x4Native(addr, bus_number=kwargs.get('bus_number', 1), bus=kwargs.get('bus'))
        self._display.brightness = 0.20
        self._width = len(self._display.i2c_device) * 4
        self._position = 0
        self._pending_show = False  # true when the buffer has unsent changes
        self._clear_line()

    def set_brightness(self, brightness: float) -> None:
        self._display.brightness = brightness

    @property
    def Seg14x4(self) -> Seg14x4Native:
        return self._display

    @property
    def Width(self) -> int:
        return self._width

    def _clear_line(self):
        self._display.fill(0)
        self._position = 0
        self._pending_show = False
        self._display.show()

    def clear(self):
        self._clear_line()

    def write(self, text: str):
        '''Write text at the current cursor position.
        Buffers all characters and defers show() until flush() is called,
        which avoids a costly I2C transaction for every single character.'''
        for char in text:
            if self._position >= self._width:  # fixed: was >, now >=
                break
            if char == '.' and self._position > 0:
                self._position -= 1
            self._display._put(char, self._position)
            self._position += 1
        self._pending_show = True

    def write_at_position(self, position: int, text: str, dp: bool = False):
        '''Write text at a specific position, optionally also lighting the
        decimal-point segment on that same cell. Bypasses write()'s own
        per-'.' cursor-decrement handling -- by the time a caller reaches
        this method, any '.'/',' has already been folded upstream (see
        animations.text.period_fold.fold_periods) into an explicit dp
        flag rather than a literal character, so there's no cursor
        adjustment to make here.'''
        self.set_position(position)
        self.write(text)
        if dp and position < self._width:
            # _put()'s '.' handling ORs the DP bit into whatever's already
            # at the given index rather than overwriting it.
            self._display._put('.', position)
            self._pending_show = True

    def flush(self):
        '''Send buffered changes to the hardware in a single I2C transaction.
        Call once per draw cycle after all write() calls are complete.'''
        if self._pending_show:
            self._display.show()
            self._pending_show = False

    def set_position(self, position: int):
        '''Set the cursor position on the display.'''
        self._position = position
