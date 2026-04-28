import logging
from .pd1200Driver import pd1200Driver
import asyncio
from .. import abstract_line_display

class pd1200LineDisplay(abstract_line_display.AbstractSingleLineDisplay):
    def __init__(self, driver: pd1200Driver, **kwargs) -> None:
        self._driver = driver
        self._line = kwargs.get('line', 0)
        self._logger = logging.getLogger(__class__.__name__ + f' Line:{self._line}')
        self._position : int = 0
    @property
    def Width(self) -> int:
        return self._driver.width

    async def clear(self):
        async with self._driver.Lock:
            await self._driver.set_position(0, self._line)
            self._position = 0
            await self._driver.clear_to_eol()

    async def write(self, text: str):
        async with self._driver.Lock:
            #self._logger.debug(f'write last_position {self._last_position} text: {text}')
            if self._position >= self.Width:
                #self._logger.debug('Already exceeds max width')
                return
            await self._driver.set_position(self._position, self._line)
            
            await self._driver.write_bytes(text.encode('ascii', errors='ignore'))
            self._position += len(text)
            #self._logger.debug(f'last position = {self._position}')

    async def set_position(self, position: int):
        self._position = position
        await asyncio.sleep(0)

    async def write_at_position(self, text: str, position: int):
        '''Write text to the display at a specific position.'''
        async with self._driver.Lock:
            await self._driver.set_position(position, self._line)
            await self.write(text=text)