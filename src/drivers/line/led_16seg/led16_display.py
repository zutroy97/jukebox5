import logging
import asyncio
from .. import abstract_line_display

from busio import I2C
import board
from adafruit_ht16k33 import segments

class led16_display(abstract_line_display.AbstractSingleLineDisplay):

    def __init__(
            self, 
            **kwargs) -> None:
        self._logger = logging.getLogger(__class__.__name__)
        i2c = kwargs.get('i2c', I2C(board.SCL, board.SDA))
        addr = kwargs.get('addr', (0x72, 0x73, 0x74))
        self._display = segments.Seg14x4(i2c, address=addr)  # uses board.SCL and board.SDA
        self._display.brightness = 0.20
        self._width = len(self._display.i2c_device) * 4
        self._position = 0
        self._clear_line()
   
    def set_brightness(self, brightness: float) -> None:
        self._display.brightness = brightness

    @property
    def Seg14x4(self) -> segments.Seg14x4:
        return self._display
    
    @property
    def Width(self):
        return self._display.i2c_device * 4
        self._logger = logging.getLogger(__class__.__name__ )

    def _clear_line(self):
        self._display.fill(0)
        self._position = 0

    async def clear(self):
        self._clear_line()

    async def write(self, text: str):
        for char in text:
            if self._position > self.Width:
                break # Can't display anyhow
            #self._logger.debug(f'{self._position} char: {char}')
            if char == '.' and self._position > 0:
                self._position -= 1
            self._display._put(char, self._position)
            self._position += 1
        #self._logger.debug(f'last position = {self._position}')
        self._display.show()

    async def set_position(self, position: int):
        '''Set the cursor position on the display.'''
        self._position = position

    @property
    def Width(self) -> int:
        '''Get the width of the display.'''
        return self._width    
