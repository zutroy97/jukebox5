
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
    
    @staticmethod
    async def default_on_clear_display(observer: "SingleLineAnimatedSimpleObserver") -> bool:
        '''Default callback for clearing the display. Can be overridden by setting the on_clear_display_callback attribute.'''
        await observer._driver.clear()
        return True

    
    async def default_on_line_animation_finished(self, observer: SingleLineAnimatedSimpleObserver) -> bool:
        if not hasattr(self, "_default_on_line_animation_finished_timer"):
            self._default_on_line_animation_finished_timer : float = time.monotonic() + 2.0
        if time.monotonic() < self._default_on_line_animation_finished_timer:
            return False
        delattr(self, "_default_on_line_animation_finished_timer")
        return True
    
    async def default_on_animation_finished(self, observer: SingleLineAnimatedSimpleObserver) -> bool:
        if len(observer._text) <= observer._driver.Width:
            # If the text fits on the display, we can just stay idle until the next update.
            # If it doesn't fit, we should restart the animation after a delay to keep it moving.
            observer._state = self.State.IDLE
            return True
        else:
            if not hasattr(self, "_default_on_animation_finished_timer"):
                self._default_on_animation_finished_timer : float = time.monotonic() + 4.0
            if time.monotonic() < self._default_on_animation_finished_timer:
                return False
            # If the text doesn't fit on the display, we should restart 
            # the animation after a delay to keep it moving.
            await observer._text_generator.Start()
            observer._state = self.State.START_ANIMATION
            delattr(self, "_default_on_animation_finished_timer")
            return True    
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._driver : abstract_line_display = kwargs.get('driver', None)
        self._event_type : UpdateEventType = kwargs.get('event_type', None)
        self._text : str = ""
        self._timer : float = 0.0
        self._state : SingleLineAnimatedSimpleObserver.State = self.State.IDLE
        self._prevState : SingleLineAnimatedSimpleObserver.State = self.State.IDLE
        self._line_animation : AbstractTextAnimator = Slide()
        self._on_character_write_callback : Callable[[SingleLineAnimatedSimpleObserver, int, str], Awaitable[bool]] = self._default_on_character_write_callback
        self._on_clear_display_callback : Callable[[SingleLineAnimatedSimpleObserver], Awaitable[bool]] = self.default_on_clear_display
        self.delay_between_characters_s : float = 0.105
        '''Delay in seconds between writing each character during the animation. Can be adjusted to speed up or slow down the animation.'''
        self.on_line_animation_finished : Callable[[SingleLineAnimatedSimpleObserver], Awaitable[bool]] = self.default_on_line_animation_finished
        self.on_animation_finished : Callable[[SingleLineAnimatedSimpleObserver], Awaitable[bool]] = self.default_on_animation_finished

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

    def setClearDisplayCallback(self, callback: Callable[[SingleLineAnimatedSimpleObserver], Awaitable[bool]]):
        '''Sets the callback function to be called when the display needs to be cleared. The callback should return True if the clear was successful, or False if it failed.'''
        self._on_clear_display_callback = callback

    def changeAnimation(self, anim_type: AbstractTextAnimator):
        '''Changes the animation type for this observer. The new animation will be used the next time the text is updated.'''
        self._line_animation = anim_type
        self._state = self.State.TEXT_UPDATED # forces animation to be recreated with new type

    async def shutdown(self, message: str, **kwargs) -> None:
        '''Called when a shutdown event is received'''
        await self._on_clear_display_callback(self)

    async def draw(self) -> None:
        self._loopNow = time.monotonic()
        # if self._state not in [self.State.IDLE, self.State.ANIMATION_DELAY] and self._state != self._prevState:
        #     self._logger.debug(f"{self._event_type} State changed from {self._prevState} to {self._state}")
        #     self._prevState = self._state

        if self._state is self.State.TEXT_UPDATED:
            self._text_generator = MultiLineGenerator(text=self._text, max_text_width=self._driver.Width)
            await self._text_generator.Start()
            self._state = self.State.START_ANIMATION

        if self._state is self.State.START_ANIMATION:
            if await self._on_clear_display_callback(self):
                # Clear was successful, we can start the animation immediately
                await self._createAnimation()
                self._state = self.State.ANIMATING

        if self._state is self.State.ANIMATING: # ensures text has been set and animation has been created
            next = await self._line_animation.Next()
            if next:
                text = await self._line_animation.GetText()
                chars = self._diff.getDiff(text)
                for pos, c in chars:
                    #self._logger.debug(f"Writing character '{c}' at position {pos}")
                    await self._on_character_write_callback(self, pos, c)
                self.setDelaySeconds(self.delay_between_characters_s)
                self._state = self.State.ANIMATION_DELAY
            else:
                if await self._text_generator.Next():
                    # More lines to generate
                    self._state = self.State.ANIMATION_LINE_FINISHED
                else:
                    self._state = self.State.ANIMATION_FINISHED

        if self._state is self.State.ANIMATION_LINE_FINISHED:
            if await self.on_line_animation_finished(self):
                '''Line animation finished successfully, we can proceed to the next line or finish the animation'''                        
                self._state = self.State.START_ANIMATION
        elif self._state is self.State.ANIMATION_FINISHED:
            await self.on_animation_finished(self)

        self._setStateIfTimerElapsed(SingleLineAnimatedSimpleObserver.State.ANIMATION_DELAY
                                        , SingleLineAnimatedSimpleObserver.State.ANIMATING)



    def setDelaySeconds(self, seconds: float):
        self._delay_s = seconds
        self._timer = time.monotonic() + seconds

    def _setStateIfTimerElapsed(self, currentState: State, newState: State) -> bool:
        '''Checks if the timer has elapsed and if the current state matches the expected state, then updates the state to the new state. Returns True if the state was updated, False otherwise.'''
        if self._state is not currentState:
            return False
        if self._timer > self._loopNow:
            return False
        self._state = newState
        return True
    
    async def _createAnimation(self) -> None:
        '''Creates the animation for the current text. Assumes that the text generator has already been initialized and started.'''
        initial_text = ''
        if await self._text_generator.Next():
            initial_text = await self._text_generator.GetText()
        #self._logger.debug(f"Starting animation with text: {initial_text}")
        await self._line_animation.StartWithText(initial_text)
        self._diff = TextDiff()
