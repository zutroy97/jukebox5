import asyncio
import logging

from busio import I2C
import board
from adafruit_ht16k33 import segments

class led16_driver:
    def __init__(
            self, 
            **kwargs) -> None:
        self._logger = logging.getLogger(__class__.__name__)
        i2c = kwargs.get('i2c', I2C(board.SCL, board.SDA))
        addr = kwargs.get('addr', (0x72, 0x73, 0x74))
        self._display = segments.Seg14x4(i2c, address=addr)  # uses board.SCL and board.SDA
        self._display.brightness = 0.20

    def clear(self):
        self._display.fill(0)
    
    def set_brightness(self, brightness: float) -> None:
        self._display.brightness = brightness

    @property
    def Seg14x4(self) -> segments.Seg14x4:
        return self._display
    
    @property
    def Width(self):
        return self._display.i2c_device * 4
    

