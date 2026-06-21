from abc import abstractmethod, ABC
import logging
# Avoid importing observers at module import time to prevent circular imports.
from typing import TYPE_CHECKING
import time

from observers.observer_states import ObserverStates

if TYPE_CHECKING:
    from observers.text.single_text_line_animated import SingleTextLineAnimatedObserver

class AbstractClearTextAnimator(ABC):
    def __init__(self) -> None:
        super().__init__()
        self._finishedState : ObserverStates = ObserverStates.DISPLAY_CLEARED
        self._observer : "SingleTextLineAnimatedObserver"

    @abstractmethod
    async def Handle(self, textAnimator: "SingleTextLineAnimatedObserver") -> None:
        self._observer = textAnimator

    @property
    def StateWhenFinished(self) -> ObserverStates:
        return self._finishedState
    
    @StateWhenFinished.setter
    def StateWhenFinished(self, value: ObserverStates):
        self._finishedState = value

       
class ClearTextImmediatelyAnimator(AbstractClearTextAnimator):
    async def Handle(self, textAnimator: "SingleTextLineAnimatedObserver") -> None:
        if textAnimator._state in [ObserverStates.DISPLAY_CLEARING_START, ObserverStates.DISPLAY_CLEARING] :
            textAnimator._state = self._finishedState
            await textAnimator.DisplayDriver.clear()

class ClearTextBlankLeftToRightAnimator(AbstractClearTextAnimator):
    def __init__(self):
        self._animation_clear_segment : int = 0
        self._next_animation_tick : float = 0.0
        self.delay_between_characters_s : float = 0.0010

    async def Handle(self, textAnimator: "SingleTextLineAnimatedObserver") -> None:
        await super().Handle(textAnimator)
        if self._observer._state is ObserverStates.DISPLAY_CLEARING_START:
            await self.on_state_display_clearing_start()
        elif self._observer._state is ObserverStates.DISPLAY_CLEARING:
            await self.on_state_display_clearing()

    async def on_state_display_clearing_start(self) -> None:
        '''Called when the state changes to DISPLAY_CLEARING_START.'''
        self._animation_clear_segment = 0
        self._next_animation_tick = time.monotonic() + self.delay_between_characters_s        
        self._observer._state = ObserverStates.DISPLAY_CLEARING

    async def on_state_display_clearing(self) -> None:
        '''Called when the state is DISPLAY_CLEARING. Must eventually transition to DISPLAY_CLEARED.'''
        if self._animation_clear_segment >= self._observer.DisplayDriver.Width:
            self._observer._state = self._finishedState
            return
        if time.monotonic() >= self._next_animation_tick:
            await self._observer.DisplayDriver.write_at_position(self._animation_clear_segment, ' ')
            self._animation_clear_segment += 1
            self._next_animation_tick = time.monotonic() + self.delay_between_characters_s

