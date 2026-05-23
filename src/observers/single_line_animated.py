
import asyncio
from typing import Awaitable, Callable, Type

from animations import AbstractTextAnimator, AnimationChain, AnimationChainLink, MultiLineGenerator, Slide, TextDiff, RandomTypeWriter

from .observer_base import UpdateEventType, ObserverBase
from drivers import abstract_line_display

from enum import Enum
from datetime import datetime, timedelta

class SingleLineAnimatedObserver(ObserverBase):
    class State(Enum):
        IDLE = 0
        ANIMATING = 1
        TEXT_UPDATED = 2
        ANIMATION_FINISHED = 3
        ANIMATION_LINE_FINISHED = 4
        START_ANIMATION = 5
        ANIMATION_DELAY = 6
        # CHARACTER_ANIMATION_BEGIN = 7
        # CHARACTER_ANIMATING = 8
        # CHARACTER_ANIMATION_FINISHED = 9

    @staticmethod
    async def _default_on_character_write_callback(observer: "SingleLineAnimatedObserver", pos: int, c: str) -> bool:
        await observer._driver.write_at_position(pos, c)
        return True
    
    async def on_animation_finished(self, anim: abstract_line_display) -> bool:
        self._state = self.State.ANIMATION_FINISHED
        self._timer = datetime.now() + timedelta(seconds=2)
        return True 

    async def on_animation_line_finished(self, anim: abstract_line_display) -> bool:
        #print(f"Animation line finished! - {anim.text}")
        self._state = self.State.ANIMATION_LINE_FINISHED
        self._timer = datetime.now() + timedelta(seconds=1)
        return True

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._driver : abstract_line_display = kwargs.get('driver', None)
        self._event_type : UpdateEventType = kwargs.get('event_type', None)
        self._text : str = ""
        self._anim = None
        self._diff = TextDiff()
        self._state : SingleLineAnimatedObserver.State = self.State.IDLE
        self._prevState : SingleLineAnimatedObserver.State = self.State.IDLE
        self._timer : datetime = datetime.now()
        self._loopNow : datetime = datetime.now()
        self._line_animation : Type[AbstractTextAnimator] = Slide
        self._on_character_write_callback : Callable[[SingleLineAnimatedObserver, int, str], Awaitable[bool]] = self._default_on_character_write_callback


    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        '''Called when an update is received'''
        if self._event_type is None:
            return
        if update_type is UpdateEventType.SHUTDOWN:
            #print(f"Received shutdown event with message: {kwargs.get('value', 'Shutting down')}")
            self._is_running = False
            return
        if update_type != self._event_type:
            return
    
        value = kwargs.get('value', self._text)
        if value != self._text:
            self._text = value
            #print(f"Received update for event type {update_type} with value: {value}")
            self._state = self.State.TEXT_UPDATED

    def changeAnimation(self, anim_type: Type[AbstractTextAnimator]):
        self._line_animation = anim_type
        self._state = self.State.TEXT_UPDATED

    async def loop(self) -> None:
        while self._is_running:
            self._loopNow = datetime.now()
            # if self._state not in [self.State.IDLE, self.State.ANIMATION_DELAY] and self._state != self._prevState:
            #     print(f"State changed from {self._prevState} to {self._state}")
            #     self._prevState = self._state

            if self._state is self.State.TEXT_UPDATED:
#                print(f"Creating animation for text: {self._text}")
                await self._createAnimation()
                self._state = self.State.START_ANIMATION

            elif self._state is self.State.START_ANIMATION:
                await self._driver.clear()
                await self._anim.Start()
                self._state = self.State.ANIMATING

            elif self._state is self.State.ANIMATING: # ensures text has been set and animation has been created
                next = await self._anim.Next()
                if next and self._state == self.State.ANIMATING: # ensures state hasn't changed while waiting for next
                    text = await self._anim.GetText()
                    chars = self._diff.getDiff(text)
                    for pos, c in chars:
                        await self._on_character_write_callback(self, pos, c)
                        #await self._driver.write_at_position(pos, c)
                    self._timer = self._loopNow + timedelta(seconds=0.1)
                    self._state = self.State.ANIMATION_DELAY

            elif self._state is self.State.ANIMATION_FINISHED:
                if len(self._text) <= self._driver.Width:
                    self._state = self.State.IDLE
                elif self._timer < self._loopNow:
                    self._state = self.State.START_ANIMATION
                    

            self._setStateIfTimerElapsed(SingleLineAnimatedObserver.State.ANIMATION_DELAY
                                         , SingleLineAnimatedObserver.State.ANIMATING)
            
            self._setStateIfTimerElapsed(SingleLineAnimatedObserver.State.ANIMATION_LINE_FINISHED
                                             , SingleLineAnimatedObserver.State.ANIMATING)

            await asyncio.sleep(0)
        await self._driver.clear()

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
