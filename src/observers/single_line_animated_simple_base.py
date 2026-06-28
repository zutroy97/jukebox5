
from abc import abstractmethod
import asyncio
import time

from animations import AbstractTextAnimator, MultiLineGenerator, Slide, TextDiff
from observers.observer_states import ObserverStates

from .observer_base import UpdateEventType, ObserverBase
from drivers.abstract_line_display import AbstractSingleLineDisplay

class SingleLineAnimatedObserverBase(ObserverBase):
    class AnimationDelayTimer:
        def __init__(self, from_state: ObserverStates, to_state: ObserverStates, delay_s: float):
            self.from_state = from_state
            self.to_state = to_state
            self.timer = time.monotonic() + delay_s
        
        def has_elapsed(self) -> bool:
            return time.monotonic() >= self.timer
        
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        if "event_type" not in kwargs:
            raise TypeError("Missing required keyword argument: 'event_type'")

        self._event_type : UpdateEventType = kwargs['event_type']
        self._text : str = ""
        self._timer : float = 0.0
        self._state : ObserverStates = ObserverStates.IDLE
        self._prevState : ObserverStates = ObserverStates.IDLE
        self._line_animation : AbstractTextAnimator = Slide()
        self._timers : dict[ObserverStates, SingleLineAnimatedObserverBase.AnimationDelayTimer] = {}
        self.auto_loop : bool = True
        '''When the entire line has been displayed, should it restart automatically'''

        self.delay_between_characters_s : float = 0.02
        '''Delay in seconds between writing each character during the animation. Can be adjusted to speed up or slow down the animation.'''
        self.delay_after_line_finished_s : float = 2.0
        '''Delay in seconds to wait after finishing animating a line before starting the next line. Only applies if the text exceeds the display width and needs to be animated in multiple lines.'''
        self.delay_after_animation_finished_s : float = 4.0
        '''Delay in seconds to wait after finishing animating the entire text before restarting the animation. Only applies if the text exceeds the display width and needs to be animated in multiple lines.'''

    @abstractmethod
    async def on_character_write(self, pos: int, c: str) -> bool:
        '''Default callback for writing a character to the display. Can be overridden by setting the on_character_write_callback attribute.'''
        raise NotImplementedError()
    
    async def clear_display(self) -> None:
        raise NotImplementedError()

    @property
    def Value(self):
        return self._text
    
    @Value.setter
    def Value(self, text:str):
        if text != self._text:
            self._text = text
            #print(f"Received update for event type {update_type} with value: {value}")
            self._state = ObserverStates.TEXT_UPDATED        

    async def on_state_animation_finished(self) -> bool:
        if not self.auto_loop:
            self._state = ObserverStates.ANIMATION_FINISHED_DELAY
            self.addTimer(ObserverStates.ANIMATION_FINISHED_DELAY, ObserverStates.IDLE, self.delay_after_animation_finished_s) # add a timer to automatically restart the animation after a delay
            return True
        if len(self._text) <= self.DisplayWidth:
            # If the text fits on the display, we can just stay idle until the next update.
            # If it doesn't fit, we should restart the animation after a delay to keep it moving.
            self._state = ObserverStates.IDLE
        else:
            await self._text_generator.Start() # restart the text generator to loop the animation
            self._state = ObserverStates.ANIMATION_FINISHED_DELAY
            self.addTimer(ObserverStates.ANIMATION_FINISHED_DELAY, ObserverStates.ANIMATION_FINISHED_DELAY_COMPLETE, self.delay_after_animation_finished_s) # add a timer to automatically restart the animation after a delay
        return True

    def addTimer(self, from_state: ObserverStates, to_state: ObserverStates, delay_s: float):
        '''Adds a timer that will automatically transition the state from from_state to to_state after delay_s seconds.'''
        self._timers[from_state] = SingleLineAnimatedObserverBase.AnimationDelayTimer(from_state, to_state, delay_s)

    def _checkTimers(self):
        '''Checks all timers and updates the state if any timers have elapsed.'''
        for keys in list(self._timers.keys()):
            timer = self._timers[keys]
            if timer.has_elapsed():
                if self._state == timer.from_state:
                    self._state = timer.to_state
                else:
                    # If the state has already changed, we can remove the timer since it's no longer needed.
                    del self._timers[timer.from_state]


    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        '''Called when an update is received'''
        if self._event_type is None:
            return
        if update_type != self._event_type:
            return
    
        self.Value = kwargs.get('value', self._text)


    def changeAnimation(self, anim_type: AbstractTextAnimator):
        '''Changes the animation type for this observer. The new animation will be used the next time the text is updated.'''
        self._line_animation = anim_type
        if self._state is not ObserverStates.IDLE:
            self._state = ObserverStates.TEXT_UPDATED # forces animation to be recreated with new type

    async def shutdown(self, message: str, **kwargs) -> None:
        '''Called when a shutdown event is received'''
        await self.clear_display()

    async def on_state_text_updated(self) -> None:
        '''Called when the text is updated. Can be overridden by setting the on_text_updated_callback attribute.'''
        self._text_generator = MultiLineGenerator(text=self._text, max_text_width=self.DisplayWidth)
        await self._text_generator.Start()
        self._state = ObserverStates.START_ANIMATION

    async def on_state_start_animation(self) -> None:
        '''Called when the state changes to START_ANIMATION. Can be overridden by setting the on_state_start_animation_callback attribute.'''
        await self.clear_display()
        await self._createAnimation()
        self._state = ObserverStates.ANIMATING

    async def on_pre_draw(self) -> None:
        '''Called at the beginning of each draw cycle, before any state-specific logic is executed. Can be overridden by setting the on_pre_draw_callback attribute.'''
        pass

    async def on_state_animating(self) -> None:
        '''Called when the state is ANIMATING. Can be overridden by setting the on_state_animating_callback attribute.'''
        next = await self._line_animation.Next()
        if next:
            text = await self._line_animation.GetText()
            chars = self._diff.getDiff(text)
            for pos, c in chars:
                #self._logger.debug(f"Writing character '{c}' at position {pos}")
                await self.on_character_write(pos, c)
            self.addTimer(ObserverStates.ANIMATION_DELAY, ObserverStates.ANIMATING, self.delay_between_characters_s)
        else:
            if await self._text_generator.Next():   
                # More lines to generate
                self._state = ObserverStates.ANIMATION_LINE_FINISHED
            else:
                self._state = ObserverStates.ANIMATION_FINISHED

    async def on_state_animation_line_finished(self) -> None:
        self.addTimer(ObserverStates.ANIMATION_LINE_FINISHED_DELAY, ObserverStates.ANIMATION_LINE_FINISHED_DELAY_COMPLETE, self.delay_after_line_finished_s)
        self._state = ObserverStates.ANIMATION_LINE_FINISHED_DELAY
        
    async def on_state_animation_finished_delay_complete(self) -> None:
        self._state = ObserverStates.START_ANIMATION
        
    async def on_post_draw(self) -> None:
        '''Called at the end of each draw cycle, after all state-specific logic has been executed.'''
        pass

    async def on_state_animation_line_finished_delay_complete(self) -> None:
        self._state = ObserverStates.START_ANIMATION

    async def draw(self) -> None:
        self._loopNow = time.monotonic()
        # if self._state not in [self.State.IDLE, self.State.ANIMATION_DELAY] and self._state != self._prevState:
        #     self._logger.debug(f"{self._event_type} State changed from {self._prevState} to {self._state}")
        #     self._prevState = self._state

        await self.on_pre_draw()

        if self._state is ObserverStates.TEXT_UPDATED:
            await self.on_state_text_updated()

        # if self._state is ObserverStates.DISPLAY_CLEARING_START:
        #     await self.on_state_display_clearing_start()
        # if self._state is ObserverStates.DISPLAY_CLEARING:
        #     await self.on_state_display_clearing()
        # if self._state is ObserverStates.DISPLAY_CLEARED:
        #     await self.on_state_display_cleared()

        if self._state is ObserverStates.START_ANIMATION:
            await self.on_state_start_animation()
        if self._state is ObserverStates.ANIMATING: # ensures text has been set and animation has been created
            await self.on_state_animating()
        if self._state is ObserverStates.ANIMATION_LINE_FINISHED:
            await self.on_state_animation_line_finished()
        if self._state is  ObserverStates.ANIMATION_FINISHED:
            await self.on_state_animation_finished()
        if self._state is ObserverStates.ANIMATION_LINE_FINISHED_DELAY_COMPLETE:
            await self.on_state_animation_line_finished_delay_complete()
        if self._state is ObserverStates.ANIMATION_FINISHED_DELAY_COMPLETE:
            await self.on_state_animation_finished_delay_complete()

        await self.on_post_draw()
        self._checkTimers() # ensure timers are checked at the end of the draw cycle as well, in case any state changes occurred that would affect the timers 

    async def _createAnimation(self) -> None:
        '''Creates the animation for the current text. Assumes that the text generator has already been initialized and started.'''
        initial_text = ''
        if await self._text_generator.Next():
            initial_text = await self._text_generator.GetText()
        #self._logger.debug(f"Starting animation with text: {initial_text}")
        self._line_animation.max_text_width = self.DisplayWidth
        await self._line_animation.StartWithText(initial_text)
        self._diff = TextDiff()
