import time
from abc import abstractmethod
from typing import Optional

from animations import AbstractTextAnimator, MultiLineGenerator, Slide, TextDiff
from observer_states import ObserverStates

from .observer_base import UpdateEventType, ObserverBase

_IDLE_STATES = frozenset([
    ObserverStates.IDLE,
    ObserverStates.ANIMATION_FINISHED,
])

_TIMER_DRIVEN_STATES = frozenset([
    ObserverStates.ANIMATION_DELAY,
    ObserverStates.ANIMATION_LINE_FINISHED_DELAY,
    ObserverStates.ANIMATION_FINISHED_DELAY,
])


class _DelayTimer:
    """A one-shot 'wait delay_s, then move from_state -> to_state' timer.
    Keyed by from_state in SingleLineAnimatedObserverBase._timers, so at most
    one of these is ever pending at a time."""

    def __init__(self, from_state: ObserverStates, to_state: ObserverStates, delay_s: float) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.deadline = time.monotonic() + delay_s

    def has_elapsed(self) -> bool:
        return time.monotonic() >= self.deadline

    def seconds_remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())


class SingleLineAnimatedObserverBase(ObserverBase):
    """Drives a small state machine that types a line of text onto a display
    one character/frame at a time, waits, then moves on.

    Subclasses (SingleTextLineAnimatedObserver, SingleLineLed16AnimatedObserver)
    only need to implement `on_character_write` and `clear_display` — the
    line-wrapping, pacing, and looping logic live entirely here.

    States fall into three buckets:
      - idle (_IDLE_STATES): nothing to do, next_wakeup() returns None.
      - timer-driven (_TIMER_DRIVEN_STATES): waiting on a `_DelayTimer`.
      - everything else ("advancing"): processed immediately by draw(), which
        keeps calling the matching on_state_* handler until the state lands
        in one of the two buckets above (see `_advance_through_states`).
    """

    # Maps a state to the name of the handler that processes it. Every state
    # not in _IDLE_STATES or _TIMER_DRIVEN_STATES must be listed here.
    _STATE_HANDLERS: dict[ObserverStates, str] = {
        ObserverStates.TEXT_UPDATED: 'on_state_text_updated',
        ObserverStates.START_ANIMATION: 'on_state_start_animation',
        ObserverStates.ANIMATING: 'on_state_animating',
        ObserverStates.ANIMATION_LINE_FINISHED: 'on_state_animation_line_finished',
        ObserverStates.ANIMATION_FINISHED: 'on_state_animation_finished',
        ObserverStates.ANIMATION_LINE_FINISHED_DELAY_COMPLETE: 'on_state_animation_line_finished_delay_complete',
        ObserverStates.ANIMATION_FINISHED_DELAY_COMPLETE: 'on_state_animation_finished_delay_complete',
    }

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        if "event_type" not in kwargs:
            raise TypeError("Missing required keyword argument: 'event_type'")

        self._event_type: UpdateEventType = kwargs['event_type']
        self._text: str = ""
        self._state: ObserverStates = ObserverStates.IDLE
        self._line_animation: AbstractTextAnimator = Slide()
        self._text_generator: MultiLineGenerator = MultiLineGenerator(text="", max_text_width=self.DisplayWidth)
        self._diff: TextDiff = TextDiff()
        self._timers: dict[ObserverStates, _DelayTimer] = {}
        self.auto_loop: bool = True

        self.delay_between_characters_s: float = 0.02
        self.delay_after_line_finished_s: float = 2.0
        self.delay_after_animation_finished_s: float = 4.0

    # ------------------------------------------------------------------
    # next_wakeup
    # ------------------------------------------------------------------

    def next_wakeup(self) -> Optional[float]:
        if self._state in _IDLE_STATES:
            return None
        if self._state in _TIMER_DRIVEN_STATES:
            timer = self._timers.get(self._state)
            return timer.seconds_remaining() if timer is not None else 0.0
        # Any other state is advanced immediately by draw() — wake now.
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

    def addTimer(self, from_state: ObserverStates, to_state: ObserverStates, delay_s: float) -> None:
        self._timers[from_state] = _DelayTimer(from_state, to_state, delay_s)

    def _checkTimers(self) -> None:
        for from_state, timer in list(self._timers.items()):
            if not timer.has_elapsed():
                continue
            del self._timers[from_state]
            if self._state == from_state:
                self._state = timer.to_state

    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        # Intentionally does not call super().UpdateReceived(): this is a
        # single-purpose leaf display (one artist/title/etc. field) that
        # only ever reacts to its own configured event type. It doesn't
        # participate in message-rotation — KeyValueTextObserver owns that
        # at the composite level.
        if self._event_type is None or update_type != self._event_type:
            return
        self.Value = kwargs.get('value', self._text)

    def changeAnimation(self, anim_type: AbstractTextAnimator) -> None:
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
        if not self._line_animation.Next():
            self._advance_past_current_line()
            return
        text = self._line_animation.GetText()
        for pos, c in self._diff.getDiff(text):
            self.on_character_write(pos, c)
        self._schedule_character_delay()

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
    # Shared by subclasses that render one "frame" per delay_between_characters_s
    # tick (SingleTextLineAnimatedObserver writes one diffed character at a
    # time; SingleLineLed16AnimatedObserver writes one buffered segment frame
    # at a time). Centralizing this trio means the from_state/to_state/
    # self._state can't drift out of sync — a bug here previously left
    # self._state stuck at ANIMATING forever, which made next_wakeup() return
    # 0.0 on every tick and busy-looped the coordinator thread.
    # ------------------------------------------------------------------

    def _schedule_character_delay(self) -> None:
        """Pause in ANIMATING for delay_between_characters_s before resuming."""
        self._state = ObserverStates.ANIMATION_DELAY
        self.addTimer(ObserverStates.ANIMATION_DELAY,
                      ObserverStates.ANIMATING,
                      self.delay_between_characters_s)

    def _advance_past_current_line(self) -> None:
        """Called once the current line has no more character/frame data.
        has_more() tells us if the generator has further lines without
        consuming them — the next _createAnimation() call (via
        START_ANIMATION) fetches the next one."""
        if self._text_generator.has_more():
            self._state = ObserverStates.ANIMATION_LINE_FINISHED
        else:
            self._state = ObserverStates.ANIMATION_FINISHED

    # ------------------------------------------------------------------
    # Draw loop
    # ------------------------------------------------------------------

    def draw(self) -> None:
        if self._state in _IDLE_STATES:
            return

        timer_still_pending = False
        if self._state in _TIMER_DRIVEN_STATES:
            self._checkTimers()
            timer_still_pending = self._state in _TIMER_DRIVEN_STATES

        if not timer_still_pending:
            self.on_pre_draw()
            self._advance_through_states()

        # Always run on_post_draw — subclass clear animator lives here.
        self.on_post_draw()
        self._checkTimers()

    def _advance_through_states(self) -> None:
        """Repeatedly dispatch to the handler for the current state until it
        lands on an idle or timer-driven state. Each handler is expected to
        change self._state; if one doesn't, we stop and log a warning
        instead of spinning on the same state forever."""
        while self._state in self._STATE_HANDLERS:
            state_before = self._state
            handler = getattr(self, self._STATE_HANDLERS[state_before])
            handler()
            if self._state == state_before:
                self._logger.warning(
                    "%s: on_state handler for %s did not change the state — "
                    "stopping here instead of spinning",
                    self.__class__.__name__, state_before,
                )
                break

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
