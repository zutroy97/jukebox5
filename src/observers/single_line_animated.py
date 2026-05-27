
import asyncio
import time
from typing import Awaitable, Callable, Type

from animations import AbstractTextAnimator, AnimationChain, AnimationChainLink, MultiLineGenerator, Slide, TextDiff, RandomTypeWriter

from .observer_base import UpdateEventType, ObserverBase
from drivers import abstract_line_display

from enum import Enum

class SingleLineAnimatedObserver(ObserverBase):
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
        # CHARACTER_ANIMATION_BEGIN = 7
        # CHARACTER_ANIMATING = 8
        # CHARACTER_ANIMATION_FINISHED = 9

    @staticmethod
    async def _default_on_character_write_callback(observer: "SingleLineAnimatedObserver", pos: int, c: str) -> bool:
        await observer._driver.write_at_position(pos, c)
        return True
    
    async def on_animation_finished(self, anim: abstract_line_display) -> bool:
        self._state = self.State.ANIMATION_FINISHED
        self.setDelaySeconds(2.0)
        return True 

    async def on_animation_line_finished(self, anim: abstract_line_display) -> bool:
        self._state = self.State.ANIMATION_LINE_FINISHED
        self._diff = TextDiff()
        self.setDelaySeconds(1.0)
        return True

    async def on_clear_display(self):
        await self._driver.clear()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._driver : abstract_line_display = kwargs.get('driver', None)
        self._event_type : UpdateEventType = kwargs.get('event_type', None)
        self._text : str = ""
        self._anim = None
        self._diff = TextDiff()
        self._state : SingleLineAnimatedObserver.State = self.State.IDLE
        self._prevState : SingleLineAnimatedObserver.State = self.State.IDLE
        self._timer : float = time.monotonic()
        self._loopNow : float = time.monotonic()
        self._line_animation : Type[AbstractTextAnimator] = Slide
        self._on_character_write_callback : Callable[[SingleLineAnimatedObserver, int, str], Awaitable[bool]] = self._default_on_character_write_callback
        self._delay_s : float = 0.1
        self._text_update_event = asyncio.Event()

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
            self._text_update_event.set()

    def changeAnimation(self, anim_type: Type[AbstractTextAnimator]):
        self._line_animation = anim_type
        self._state = self.State.TEXT_UPDATED

    async def shutdown(self, message: str, **kwargs) -> None:
        '''Called when a shutdown event is received'''
        self._is_running = False
        self._text_update_event.set()
        await self.on_clear_display()

    async def loop(self) -> None:
        while self._is_running:
            self._loopNow = time.monotonic()
            # if self._state not in [self.State.IDLE, self.State.ANIMATION_DELAY] and self._state != self._prevState:
            #     print(f"State changed from {self._prevState} to {self._state}")
            #     self._prevState = self._state

            if self._state is self.State.TEXT_UPDATED:
#                print(f"Creating animation for text: {self._text}")
                await self._createAnimation()
                self._state = self.State.START_ANIMATION
                continue

            elif self._state is self.State.START_ANIMATION:
                await self.on_clear_display()
                await self._anim.Start()
                self._diff = TextDiff()
                self._state = self.State.ANIMATING
                continue

            elif self._state is self.State.ANIMATING: # ensures text has been set and animation has been created
                next = await self._anim.Next()
                if next and self._state == self.State.ANIMATING: # ensures state hasn't changed while waiting for next
                    text = await self._anim.GetText()
                    chars = self._diff.getDiff(text)
                    for pos, c in chars:
                        await self._on_character_write_callback(self, pos, c)
                    self.setDelaySeconds(0.01)
                    self._state = self.State.ANIMATION_DELAY

            elif self._state is self.State.ANIMATION_FINISHED:
                if len(self._text) <= self._driver.Width:
                    self._state = self.State.IDLE
                    self.setDelaySeconds(10.0)
                elif self._timer < self._loopNow:
                    self._state = self.State.START_ANIMATION
                    continue
            
            
            self._setStateIfTimerElapsed(SingleLineAnimatedObserver.State.ANIMATION_DELAY
                                         , SingleLineAnimatedObserver.State.ANIMATING)
            
            self._setStateIfTimerElapsed(SingleLineAnimatedObserver.State.ANIMATION_LINE_FINISHED
                                             , SingleLineAnimatedObserver.State.ANIMATING)

            #print(f"State: {self._state}, Timer: {self._timer}, LoopNow: {self._loopNow}, Sleeping for: {self._delay_s} seconds")
            try:
                await asyncio.wait_for(
                    self._text_update_event.wait(),
                    timeout=self._delay_s
                )
                self._text_update_event.clear()
            except asyncio.TimeoutError:
                pass


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
    
    async def _createAnimation(self) -> AnimationChain:
        #print(f"Creating animation chain for text: {self._text}")
        self._anim = AnimationChain(
            max_text_width=self._driver.Width,
            links=[
                AnimationChainLink(MultiLineGenerator, onFinished=self.on_animation_finished),
                AnimationChainLink(self._line_animation, onFinished=self.on_animation_line_finished),
            ], text=self._text)
        self._diff = TextDiff()
