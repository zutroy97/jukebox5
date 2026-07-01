from animations.led_16.abstract_led16_animator import AbstractLED16Animator
from animations.led_16.alien import AlienAnimator
from animations.led_16.led16_static import LED16Static
from animations.text.static import Static

from ..single_line_animated_simple_base import SingleLineAnimatedObserverBase
from adafruit_ht16k33 import segments
from observers.observer_states import ObserverStates

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
        if len(self._segment_list) == 0:
            if self._line_animation.Next():
                text = self._line_animation.GetText()
                self._segment_animation.text = text
                self._segment_animation.Start()
                while self._segment_animation.Next():
                    self._segment_list.append(self._segment_animation.GetSegments())
            elif self._text_generator.has_more():
                # More lines to generate. has_more() doesn't consume the line —
                # the next _createAnimation() call (via START_ANIMATION) fetches it.
                self._state = ObserverStates.ANIMATION_LINE_FINISHED
            else:
                self._state = ObserverStates.ANIMATION_FINISHED
            return
        i = 0
        for seg in self._segment_list.pop(0):
            self._driver.set_digit_raw(i, seg)
            i += 1
        self._driver.show()
        
        self._state = ObserverStates.ANIMATION_DELAY
        self.addTimer(ObserverStates.ANIMATION_DELAY, ObserverStates.ANIMATING, self.delay_between_characters_s)


