import time
from typing import Optional

from observer_states import ObserverStates
from observers.single_line_animated_simple_base import SingleLineAnimatedObserverBase
from drivers.abstract_line_display import AbstractSingleLineDisplay
from animations.abstract_clear_animator import AbstractClearTextAnimator, ClearTextImmediatelyAnimator
from animations.abstract_character_reveal_animator import (
    AbstractCharacterRevealAnimator,
    CharacterRevealImmediatelyAnimator,
)

_CLEARING_STATES = frozenset([
    ObserverStates.DISPLAY_CLEARING_START,
    ObserverStates.DISPLAY_CLEARING,
])


class SingleTextLineAnimatedObserver(SingleLineAnimatedObserverBase):
    '''An observer that displays a single line of text with animation.'''

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'driver'")
        self._driver: AbstractSingleLineDisplay = kwargs['driver']
        self.DisplayWidth = self._driver.Width
        self._clearDisplayAnimation: AbstractClearTextAnimator = ClearTextImmediatelyAnimator()
        self._characterRevealAnimation: AbstractCharacterRevealAnimator = CharacterRevealImmediatelyAnimator()
        # Positions still to write for the current animation tick, in order --
        # see _advance_character_writes(). Normally has at most one entry
        # (the animators driving _line_animation produce one new character
        # per tick), but is handled as a queue in case more than one
        # position ever changes in the same tick.
        self._pending_character_writes: list[tuple[int, str]] = []

    def next_wakeup(self) -> Optional[float]:
        # During clear animation, sleep until the animator's next tick.
        if self._state in _CLEARING_STATES:
            anim = self._clearDisplayAnimation
            if hasattr(anim, '_next_animation_tick'):
                return max(0.0, anim._next_animation_tick - time.monotonic())
            # ClearTextImmediatelyAnimator has no tick — it runs instantly, wake now.
            return 0.0
        # During a multi-tick character reveal, sleep until its next segment.
        if self._state == ObserverStates.CHARACTER_REVEALING:
            anim = self._characterRevealAnimation
            if hasattr(anim, '_next_tick'):
                return max(0.0, anim._next_tick - time.monotonic())
            return 0.0
        return super().next_wakeup()

    def on_character_write(self, pos: int, c: str) -> bool:
        return self._characterRevealAnimation.Start(self, pos, c)

    def clear_display(self) -> None:
        self._state = ObserverStates.DISPLAY_CLEARING_START
        self.ClearDisplayAnimation.StateWhenFinished = ObserverStates.START_ANIMATION

    def on_state_text_updated(self) -> None:
        super().on_state_text_updated()
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

    @property
    def CharacterRevealAnimation(self) -> AbstractCharacterRevealAnimator:
        return self._characterRevealAnimation

    @CharacterRevealAnimation.setter
    def CharacterRevealAnimation(self, value: AbstractCharacterRevealAnimator):
        self._characterRevealAnimation = value

    def on_state_animation_finished_delay_complete(self) -> None:
        self.ClearDisplayAnimation.StateWhenFinished = ObserverStates.START_ANIMATION
        self._state = ObserverStates.DISPLAY_CLEARING_START

    def on_state_start_animation(self) -> None:
        self._createAnimation()
        self._state = ObserverStates.ANIMATING

    def on_state_animating(self) -> None:
        '''Overrides the base class's default (which writes each diffed
        position in one shot and immediately schedules the next tick) so a
        CharacterRevealAnimation that needs multiple ticks per character
        (e.g. SegmentByCharacterRevealAnimator) can park in
        CHARACTER_REVEALING until it finishes -- see _advance_character_writes().'''
        if not self._line_animation.Next():
            self._advance_past_current_line()
            return
        text = self._line_animation.GetText()
        self._pending_character_writes = self._diff.getDiff(text)
        self._advance_character_writes()

    def _advance_character_writes(self) -> None:
        '''Starts/resumes revealing queued character writes one at a time --
        each fully finishes before the next one starts. Once the queue is
        empty, falls through to the normal inter-character delay, exactly
        like the base class's default on_state_animating() did for an
        instant write.'''
        while self._pending_character_writes:
            pos, c = self._pending_character_writes[0]
            if not self.on_character_write(pos, c):
                self._state = ObserverStates.CHARACTER_REVEALING
                return
            self._pending_character_writes.pop(0)
        self._schedule_character_delay()

    def on_post_draw(self) -> None:
        # The clear animator handles DISPLAY_CLEARING_START and DISPLAY_CLEARING.
        self._clearDisplayAnimation.Handle(self)
        # The character-reveal animator handles CHARACTER_REVEALING.
        if self._state == ObserverStates.CHARACTER_REVEALING:
            if self._characterRevealAnimation.Handle(self):
                self._pending_character_writes.pop(0)
                self._advance_character_writes()
        # Flush all buffered character writes in one I2C transaction.
        if hasattr(self._driver, 'flush'):
            self._driver.flush()

    def on_state_animation_line_finished_delay_complete(self) -> None:
        self.ClearDisplayAnimation.StateWhenFinished = ObserverStates.START_ANIMATION
        self._state = ObserverStates.DISPLAY_CLEARING_START
