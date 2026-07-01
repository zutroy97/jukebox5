from abc import abstractmethod
import time
from typing import Optional

from animations import AbstractTextAnimator, MultiLineGenerator, Slide, TextDiff
from observers.observer_states import ObserverStates

from .observer_base import UpdateEventType, ObserverBase

_TRULY_IDLE_STATES = frozenset([
    ObserverStates.IDLE,
    ObserverStates.ANIMATION_FINISHED,
])

_TIMER_DRIVEN_STATES = frozenset([
    ObserverStates.ANIMATION_DELAY,
    ObserverStates.ANIMATION_LINE_FINISHED_DELAY,
    ObserverStates.ANIMATION_FINISHED_DELAY,
])


class SingleLineAnimatedObserverBase(ObserverBase):
    class AnimationDelayTimer:
        def __init__(self, from_state: ObserverStates, to_state: ObserverStates, delay_s: float):
            self.from_state = from_state
            self.to_state = to_state
            self.deadline = time.monotonic() + delay_s

        def has_elapsed(self) -> bool:
            return time.monotonic() >= self.deadline

        def seconds_remaining(self) -> float:
            return max(0.0, self.deadline - time.monotonic())

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        if "event_type" not in kwargs:
            raise TypeError("Missing required keyword argument: 'event_type'")

        self._event_type: UpdateEventType = kwargs['event_type']
        self._text: str = ""
        self._state: ObserverStates = ObserverStates.IDLE
        self._line_animation: AbstractTextAnimator = Slide()
        self._timers: dict[ObserverStates, SingleLineAnimatedObserverBase.AnimationDelayTimer] = {}
        self.auto_loop: bool = True

        self.delay_between_characters_s: float = 0.02
        self.delay_after_line_finished_s: float = 2.0
        self.delay_after_animation_finished_s: float = 4.0

    # ------------------------------------------------------------------
    # next_wakeup
    # ------------------------------------------------------------------

    def next_wakeup(self) -> Optional[float]:
        if self._state in _TRULY_IDLE_STATES:
            return None
        if self._state in _TIMER_DRIVEN_STATES:
            for timer in self._timers.values():
                if timer.from_state == self._state:
                    return timer.seconds_remaining()
            return 0.0
        return 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @abstractmethod
    def on_character_write(self, pos: int, c: str) -> bool:
        raise NotImplementedError()

    def clear_display(self) -> None:
        raise NotImplementedError()

    @property
    def Value(self):
        return self._text

    @Value.setter
    def Value(self, text: str):
        if text != self._text:
            self._text = text
            self._state = ObserverStates.TEXT_UPDATED

    def addTimer(self, from_state: ObserverStates, to_state: ObserverStates, delay_s: float):
        self._timers[from_state] = SingleLineAnimatedObserverBase.AnimationDelayTimer(
            from_state, to_state, delay_s
        )

    def _checkTimers(self):
        for key in list(self._timers.keys()):
            timer = self._timers[key]
            if timer.has_elapsed():
                if self._state == timer.from_state:
                    self._state = timer.to_state
                del self._timers[key]

    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        if self._event_type is None or update_type != self._event_type:
            return
        self.Value = kwargs.get('value', self._text)

    def changeAnimation(self, anim_type: AbstractTextAnimator):
        self._line_animation = anim_type
        if self._state is not ObserverStates.IDLE:
            self._state = ObserverStates.TEXT_UPDATED

    def shutdown(self, message: str, **kwargs) -> None:
        self.clear_display()

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def on_state_text_updated(self) -> None:
        self._text_generator = MultiLineGenerator(text=self._text, max_text_width=self.DisplayWidth)
        self._text_generator.Start()
        self._state = ObserverStates.START_ANIMATION

    def on_state_start_animation(self) -> None:
        self.clear_display()
        self._createAnimation()
        self._state = ObserverStates.ANIMATING

    def on_pre_draw(self) -> None:
        pass

    def on_state_animating(self) -> None:
        if self._line_animation.Next():
            text = self._line_animation.GetText()
            chars = self._diff.getDiff(text)
            for pos, c in chars:
                self.on_character_write(pos, c)
            self._state = ObserverStates.ANIMATION_DELAY
            self.addTimer(ObserverStates.ANIMATION_DELAY,
                          ObserverStates.ANIMATING,
                          self.delay_between_characters_s)
        else:
            # Character animation for this line is done.
            # has_more() tells us if the generator has further lines without
            # consuming them — the next _createAnimation() call will fetch them.
            if self._text_generator.has_more():
                self._state = ObserverStates.ANIMATION_LINE_FINISHED
            else:
                self._state = ObserverStates.ANIMATION_FINISHED

    def on_state_animation_line_finished(self) -> None:
        self.addTimer(ObserverStates.ANIMATION_LINE_FINISHED_DELAY,
                      ObserverStates.ANIMATION_LINE_FINISHED_DELAY_COMPLETE,
                      self.delay_after_line_finished_s)
        self._state = ObserverStates.ANIMATION_LINE_FINISHED_DELAY

    def on_state_animation_line_finished_delay_complete(self) -> None:
        self._state = ObserverStates.START_ANIMATION

    def on_state_animation_finished(self) -> None:
        if not self.auto_loop:
            self._state = ObserverStates.ANIMATION_FINISHED_DELAY
            self.addTimer(ObserverStates.ANIMATION_FINISHED_DELAY,
                          ObserverStates.IDLE,
                          self.delay_after_animation_finished_s)
            return
        if len(self._text) <= self.DisplayWidth:
            self._state = ObserverStates.IDLE
        else:
            self._text_generator.Start()
            self._state = ObserverStates.ANIMATION_FINISHED_DELAY
            self.addTimer(ObserverStates.ANIMATION_FINISHED_DELAY,
                          ObserverStates.ANIMATION_FINISHED_DELAY_COMPLETE,
                          self.delay_after_animation_finished_s)

    def on_state_animation_finished_delay_complete(self) -> None:
        self._state = ObserverStates.START_ANIMATION

    def on_post_draw(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Draw loop
    # ------------------------------------------------------------------

    def draw(self) -> None:
        if self._state in _TRULY_IDLE_STATES:
            return

        timer_still_pending = False
        if self._state in _TIMER_DRIVEN_STATES:
            self._checkTimers()
            if self._state in _TIMER_DRIVEN_STATES:
                timer_still_pending = True

        if not timer_still_pending:
            self.on_pre_draw()

            if self._state is ObserverStates.TEXT_UPDATED:
                self.on_state_text_updated()
            if self._state is ObserverStates.START_ANIMATION:
                self.on_state_start_animation()
            if self._state is ObserverStates.ANIMATING:
                self.on_state_animating()
            if self._state is ObserverStates.ANIMATION_LINE_FINISHED:
                self.on_state_animation_line_finished()
            if self._state is ObserverStates.ANIMATION_FINISHED:
                self.on_state_animation_finished()
            if self._state is ObserverStates.ANIMATION_LINE_FINISHED_DELAY_COMPLETE:
                self.on_state_animation_line_finished_delay_complete()
            if self._state is ObserverStates.ANIMATION_FINISHED_DELAY_COMPLETE:
                self.on_state_animation_finished_delay_complete()

        # Always run on_post_draw — subclass clear animator lives here.
        self.on_post_draw()
        self._checkTimers()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _createAnimation(self) -> None:
        """Fetch the next line from the generator and start the character animator."""
        initial_text = ''
        if self._text_generator.Next():
            initial_text = self._text_generator.GetText()
        self._line_animation.max_text_width = self.DisplayWidth
        self._line_animation.StartWithText(initial_text)
        self._diff = TextDiff()