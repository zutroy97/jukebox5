import time
from typing import Optional

from observers.observer_states import ObserverStates
from observers.single_line_animated_simple_base import SingleLineAnimatedObserverBase, _TRULY_IDLE_STATES
from drivers.abstract_line_display import AbstractSingleLineDisplay
from animations.abstract_clear_animator import AbstractClearTextAnimator, ClearTextImmediatelyAnimator

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

    def next_wakeup(self) -> Optional[float]:
        # During clear animation, sleep until the animator's next tick.
        if self._state in _CLEARING_STATES:
            anim = self._clearDisplayAnimation
            if hasattr(anim, '_next_animation_tick'):
                return max(0.0, anim._next_animation_tick - time.monotonic())
            # ClearTextImmediatelyAnimator has no tick — it runs instantly, wake now.
            return 0.0
        return super().next_wakeup()

    def on_character_write(self, pos: int, c: str) -> bool:
        self.DisplayDriver.write_at_position(pos, c)
        return True

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

    def on_state_animation_finished_delay_complete(self) -> None:
        self.ClearDisplayAnimation.StateWhenFinished = ObserverStates.START_ANIMATION
        self._state = ObserverStates.DISPLAY_CLEARING_START

    def on_state_start_animation(self) -> None:
        self._createAnimation()
        self._state = ObserverStates.ANIMATING

    def on_post_draw(self) -> None:
        # The clear animator handles DISPLAY_CLEARING_START and DISPLAY_CLEARING.
        self._clearDisplayAnimation.Handle(self)
        # Flush all buffered character writes in one I2C transaction.
        if hasattr(self._driver, 'flush'):
            self._driver.flush()

    def on_state_animation_line_finished_delay_complete(self) -> None:
        self.ClearDisplayAnimation.StateWhenFinished = ObserverStates.START_ANIMATION
        self._state = ObserverStates.DISPLAY_CLEARING_START