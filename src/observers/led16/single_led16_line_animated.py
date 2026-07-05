from animations.led_16.abstract_led16_animator import AbstractLED16Animator
from animations.led_16.alien import AlienAnimator
from animations.led_16.led16_static import LED16Static
from animations.text.static import Static

from ..single_line_animated_simple_base import SingleLineAnimatedObserverBase
from adafruit_ht16k33 import segments
from observer_states import ObserverStates

class SingleLineLed16AnimatedObserver(SingleLineAnimatedObserverBase):
    '''An observer that displays a single line of text with animation on a LED16 display.'''
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'driver'")
        self._driver : segments.Seg14x4 = kwargs['driver']
        self._driver.auto_write = False # We will control when to update the display
        self.DisplayWidth = self._driver._chars
        self._line_animation = Static(max_text_width=self.DisplayWidth)
        self._segment_animation : AbstractLED16Animator = AlienAnimator(max_text_width=self.DisplayWidth)
        self._segment_list :list[list[int]] = []

    def on_character_write(self, pos: int, c: str) -> bool:
        '''Default callback for writing a character to the display.'''
        self._driver._put(c, pos)
        self._driver.show()
        return True

    def clear_display(self) -> None:
        self._driver.fill(0)
        self._driver.show()

    def on_state_start_animation(self) -> None:
        '''Called when the state changes to START_ANIMATION. Can be overridden by setting the on_state_start_animation_callback attribute.'''
        self.clear_display()
        self._createAnimation()
        self._segment_list = []
        self._state = ObserverStates.ANIMATING

    def on_state_animating(self) -> None:
        '''Called when the state is ANIMATING.'''
        if not self._segment_list:
            if self._line_animation.Next():
                self._segment_animation.text = self._line_animation.GetText()
                self._segment_animation.Start()
                while self._segment_animation.Next():
                    self._segment_list.append(self._segment_animation.GetSegments())
            else:
                self._advance_past_current_line()
            return

        for i, seg in enumerate(self._segment_list.pop(0)):
            self._driver.set_digit_raw(i, seg)
        self._driver.show()

        self._schedule_character_delay()
