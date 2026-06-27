import time

from observers.observer_states import ObserverStates

from observers.single_line_animated_simple_base import SingleLineAnimatedObserverBase
from drivers.abstract_line_display import AbstractSingleLineDisplay
from animations.abstract_clear_animator import AbstractClearTextAnimator, ClearTextImmediatelyAnimator

class SingleTextLineAnimatedObserver(SingleLineAnimatedObserverBase):
    '''An observer that displays a single line of text with animation.'''
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'driver'")
        self._driver : AbstractSingleLineDisplay = kwargs['driver']
        self.DisplayWidth = self._driver.Width
        self._clearDisplayAnimation : AbstractClearTextAnimator = ClearTextImmediatelyAnimator()

    async def on_character_write(self, pos: int, c: str) -> bool:
        '''Default callback for writing a character to the display. Can be overridden by setting the on_character_write_callback attribute.'''
        await self.DisplayDriver.write_at_position(pos, c)
        return True
    
    async def clear_display(self) -> None:
        self._state = ObserverStates.DISPLAY_CLEARING_START
        self.ClearDisplayAnimation.StateWhenFinished = ObserverStates.START_ANIMATION

    async def on_state_text_updated(self) -> None:
        await super().on_state_text_updated()
        '''Called when the text is updated. Can be overridden by setting the on_text_updated_callback attribute.'''
        self.ClearDisplayAnimation.StateWhenFinished = ObserverStates.START_ANIMATION
        self._state = ObserverStates.DISPLAY_CLEARING_START

    @property
    def DisplayDriver(self) -> AbstractSingleLineDisplay:
        return self._driver
    
    @property
    def ClearDisplayAnimation(self) -> AbstractClearTextAnimator:
        return self._clearDisplayAnimation   
    
    @ClearDisplayAnimation.setter
    def ClearDisplayAnimation(self, value: AbstractClearTextAnimator):
        self._clearDisplayAnimation = value

    async def on_state_animation_finished_delay_complete(self) -> None:
        self.ClearDisplayAnimation.StateWhenFinished = ObserverStates.START_ANIMATION
        self._state = ObserverStates.DISPLAY_CLEARING_START

    async def on_state_start_animation(self) -> None:
        await self._createAnimation()
        self._state = ObserverStates.ANIMATING

    async def on_post_draw(self) -> None:
        await self._clearDisplayAnimation.Handle(self)

    async def on_state_animation_line_finished_delay_complete(self) -> None:
        self.ClearDisplayAnimation.StateWhenFinished = ObserverStates.START_ANIMATION
        self._state = ObserverStates.DISPLAY_CLEARING_START
