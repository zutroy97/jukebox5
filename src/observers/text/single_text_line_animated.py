from ..single_line_animated_simple_base import SingleLineAnimatedObserverBase
from drivers.abstract_line_display import AbstractSingleLineDisplay

class SingleTextLineAnimatedObserver(SingleLineAnimatedObserverBase):
    '''An observer that displays a single line of text with animation.'''
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'driver'")
        self._driver : AbstractSingleLineDisplay = kwargs['driver']
        self.DisplayWidth = self._driver.Width

    async def on_character_write(self, pos: int, c: str) -> bool:
        '''Default callback for writing a character to the display. Can be overridden by setting the on_character_write_callback attribute.'''
        await self._driver.write_at_position(pos, c)
        return True
    
    async def clear_display(self) -> None:
        await self._driver.clear()    