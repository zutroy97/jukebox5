
import asyncio
import time
from typing import Awaitable, Callable, Type

from animations import AbstractTextAnimator, AnimationChain, AnimationChainLink, MultiLineGenerator, Slide, TextDiff, RandomTypeWriter

from .observer_base import UpdateEventType, ObserverBase
from drivers import abstract_line_display

from enum import Enum

class SingleLineAnimatedSimpleObserver(ObserverBase):
    class State(Enum):
        IDLE = 0
        ANIMATING = 1
        TEXT_UPDATED = 2
        ANIMATION_FINISHED = 3
        ANIMATION_LINE_FINISHED = 4
        START_ANIMATION = 5
        ANIMATION_DELAY = 6
        START_DISPLAY_CLEAR = 7
        DISPLAY_CLEARING = 8
        DISPLAY_CLEARED = 9

    @staticmethod
    async def _default_on_character_write_callback(observer: "SingleLineAnimatedSimpleObserver", pos: int, c: str) -> bool:
        await observer._driver.write_at_position(pos, c)
        return True
    
    async def on_clear_display(self):
        await self._driver.clear()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._driver : abstract_line_display = kwargs.get('driver', None)
        self._event_type : UpdateEventType = kwargs.get('event_type', None)
        self._text : str = ""
        self._state : SingleLineAnimatedSimpleObserver.State = self.State.IDLE
        self._line_animation : AbstractTextAnimator = Slide()
        self._on_character_write_callback : Callable[[SingleLineAnimatedSimpleObserver, int, str], Awaitable[bool]] = self._default_on_character_write_callback


    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        '''Called when an update is received'''
        if self._event_type is None:
            return
        if update_type != self._event_type:
            return
    
        value = kwargs.get('value', self._text)
        if value != self._text:
            self._text = value
            #print(f"Received update for event type {update_type} with value: {value}")
            self._state = self.State.TEXT_UPDATED

    def changeAnimation(self, anim_type: AbstractTextAnimator):
        self._line_animation = anim_type
        self._state = self.State.TEXT_UPDATED # forces animation to be recreated with new type

    async def shutdown(self, message: str, **kwargs) -> None:
        '''Called when a shutdown event is received'''
        await self.on_clear_display()

    async def loop(self) -> None:
        while self._is_running:
            self._loopNow = time.monotonic()
            # if self._state not in [self.State.IDLE, self.State.ANIMATION_DELAY] and self._state != self._prevState:
            #     print(f"State changed from {self._prevState} to {self._state}")
            #     self._prevState = self._state

            if self._state is self.State.TEXT_UPDATED:
#                print(f"Creating animation for text: {self._text}")
                self._text_generator = MultiLineGenerator(text=self._text, max_text_width=self._driver.Width)
                await self._text_generator.Start()

                self._state = self.State.START_ANIMATION
                continue

            elif self._state is self.State.START_ANIMATION:
                await self.on_clear_display()
                await self._createAnimation()
                self._state = self.State.ANIMATING
                continue

            elif self._state is self.State.ANIMATING: # ensures text has been set and animation has been created
                next = await self._line_animation.Next()
                if next:
                    text = await self._line_animation.GetText()
                    chars = self._diff.getDiff(text)
                    for pos, c in chars:
                        #self._logger.debug(f"Writing character '{c}' at position {pos}")
                        await self._on_character_write_callback(self, pos, c)
                    self.setDelaySeconds(0.1)
                    self._state = self.State.ANIMATION_DELAY
                else:
                    self._state = self.State.ANIMATION_LINE_FINISHED
                    if await self._text_generator.Next():
                        # More lines to generate
                        await self._createAnimation()
                        continue
                    else:
                        self._state = self.State.ANIMATION_FINISHED
                        continue
            elif self._state is self.State.ANIMATION_FINISHED:
                if len(self._text) <= self._driver.Width:
                    self._state = self.State.IDLE
                    self.setDelaySeconds(10.0)
                elif self._timer < self._loopNow:
                    self._state = self.State.START_ANIMATION
                    continue
            
            
            self._setStateIfTimerElapsed(SingleLineAnimatedSimpleObserver.State.ANIMATION_DELAY
                                         , SingleLineAnimatedSimpleObserver.State.ANIMATING)
            
            self._setStateIfTimerElapsed(SingleLineAnimatedSimpleObserver.State.ANIMATION_LINE_FINISHED
                                             , SingleLineAnimatedSimpleObserver.State.ANIMATING)

            #print(f"State: {self._state}, Timer: {self._timer}, LoopNow: {self._loopNow}, Sleeping for: {self._delay_s} seconds")
            await asyncio.sleep(0.01)


    def setDelaySeconds(self, seconds: float):
        self._delay_s = seconds
        self._timer = time.monotonic() + seconds

    def _setStateIfTimerElapsed(self, currentState: State, newState: State) -> bool:
        if self._state is not currentState:
            return False
        if self._timer > self._loopNow:
            return False
        self._state = newState
        return True
    
    async def _createAnimation(self) -> None:
        #print(f"Creating animation chain for text: {self._text}")
        
        initial_text = ''
        if await self._text_generator.Next():
            initial_text = await self._text_generator.GetText()
        #self._logger.debug(f"Starting animation with text: {initial_text}")
        await self._line_animation.StartWithText(initial_text)
        self._diff = TextDiff()
