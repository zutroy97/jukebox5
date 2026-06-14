import time

from observers.observer_states import ObserverStates

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

class SingleTextLineAnimatedClearObserver(SingleLineAnimatedObserverBase):
    '''An observer that displays a single line of text with animation.'''
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'driver'")
        self._driver : AbstractSingleLineDisplay = kwargs['driver']
        self.DisplayWidth = self._driver.Width
        self._animation_clear_segment : int = 0
        self._next_animation_tick : float = 0.0

    async def on_character_write(self, pos: int, c: str) -> bool:
        '''Default callback for writing a character to the display. Can be overridden by setting the on_character_write_callback attribute.'''
        await self._driver.write_at_position(pos, c)
        return True
    
    async def clear_display(self) -> None:
        self._state = ObserverStates.DISPLAY_CLEARING_START

    async def on_state_display_clearing_start(self) -> None:
        '''Called when the state changes to DISPLAY_CLEARING_START.'''
        self._animation_clear_segment = 0
        self._next_animation_tick = time.monotonic() + self.delay_between_characters_s        
        self._state = ObserverStates.DISPLAY_CLEARING

    async def on_state_display_clearing(self) -> None:
        '''Called when the state is DISPLAY_CLEARING. Must eventually transition to DISPLAY_CLEARED.'''
        if self._animation_clear_segment >= self.DisplayWidth:
            self._state = ObserverStates.DISPLAY_CLEARED
            return
        if time.monotonic() >= self._next_animation_tick:
            await self._driver.write_at_position(self._animation_clear_segment, ' ')
            self._animation_clear_segment += 1
            self._next_animation_tick = time.monotonic() + self.delay_between_characters_s

    # async def on_state_display_clearing_start(self) -> None:
    #     '''Called when the state changes to DISPLAY_CLEARING_START.'''
    #     self._animation_clear_segment = self.DisplayWidth - 1
    #     self._next_animation_tick = time.monotonic() + self.delay_between_characters_s        
    #     self._state = ObserverStates.DISPLAY_CLEARING

    # async def on_state_display_clearing(self) -> None:
    #     '''Called when the state is DISPLAY_CLEARING. Must eventually transition to DISPLAY_CLEARED.'''
    #     if self._animation_clear_segment <= 0:
    #         self._state = ObserverStates.DISPLAY_CLEARED
    #         return
    #     if time.monotonic() >= self._next_animation_tick:
    #         await self._driver.write_at_position(self._animation_clear_segment, ' ')
    #         self._animation_clear_segment -= 1
    #         self._next_animation_tick = time.monotonic() + self.delay_between_characters_s

    async def on_state_start_animation(self) -> None:
        '''Called when the state changes to START_ANIMATION. Can be overridden by setting the on_state_start_animation_callback attribute.'''
        await self.clear_display()
        

    async def on_state_display_cleared(self) -> None:
        '''Called when the state changes to DISPLAY_CLEARED.'''
        await self._createAnimation()
        self._state = ObserverStates.ANIMATING            
               