from ..single_line_animated_simple_base import SingleLineAnimatedObserverBase
from adafruit_ht16k33 import segments

class SingleLineLed16AnimatedObserver(SingleLineAnimatedObserverBase):
    '''An observer that displays a single line of text with animation on a LED16 display.'''
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'driver'")
        self._driver : segments.Seg14x4 = kwargs['driver']
        self.DisplayWidth = self._driver._chars

    async def on_character_write(self, pos: int, c: str) -> bool:
        '''Default callback for writing a character to the display.'''
        self._driver._put(c, pos)
        self._driver.show()
        return True
    
    async def clear_display(self) -> None:
        self._driver.fill(False)    
