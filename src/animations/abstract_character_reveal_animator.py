from abc import abstractmethod, ABC
import time
from typing import TYPE_CHECKING

# Only import the observers package under TYPE_CHECKING -- it isn't needed at
# runtime here (see observer_states.py for why this package boundary matters,
# same reasoning as abstract_clear_animator.py).
if TYPE_CHECKING:
    from observers.text.single_text_line_animated import SingleTextLineAnimatedObserver


class AbstractCharacterRevealAnimator(ABC):
    """Governs how on_character_write() renders a single character once
    it's that character's turn: instantly (the default,
    CharacterRevealImmediatelyAnimator) or progressively (e.g.
    SegmentByCharacterRevealAnimator). Pluggable via
    SingleTextLineAnimatedObserver.CharacterRevealAnimation, mirroring
    AbstractClearTextAnimator/ClearDisplayAnimation's existing pattern."""

    @abstractmethod
    def Start(self, observer: "SingleTextLineAnimatedObserver", pos: int, char: str) -> bool:
        """Begin rendering `char` at `pos`. Returns True if the render
        completed synchronously (caller can move on immediately), False if
        it needs further Handle() calls to finish."""
        raise NotImplementedError()

    @abstractmethod
    def Handle(self, observer: "SingleTextLineAnimatedObserver") -> bool:
        """Advance an in-progress render by one step. Returns True once
        finished."""
        raise NotImplementedError()


class CharacterRevealImmediatelyAnimator(AbstractCharacterRevealAnimator):
    """Writes the whole character in one shot -- the original/default
    behavior, unchanged for any observer that doesn't opt into something
    else."""

    def Start(self, observer: "SingleTextLineAnimatedObserver", pos: int, char: str) -> bool:
        observer.DisplayDriver.write_at_position(pos, char)
        return True

    def Handle(self, observer: "SingleTextLineAnimatedObserver") -> bool:
        return True


class SegmentByCharacterRevealAnimator(AbstractCharacterRevealAnimator):
    """Reveals one character's 14 segments one bit at a time (in bit
    order) before the caller moves on to the next character position --
    unlike animations.led_16.AlienAnimator, which reveals every
    character's segments simultaneously across frames for a glitchy
    effect, this finishes one character completely before the next one
    starts, matching a left-to-right "materializing" typewriter look.

    Requires the observer's DisplayDriver to expose the underlying
    adafruit_ht16k33 Seg14x4 object via a `.Seg14x4` property (see
    drivers/led16_display.py) for raw per-segment writes -- there's no way
    to light individual segments through the character-based write_at_position
    API alone.
    """

    def __init__(self, delay_between_segments_s: float = 0.02) -> None:
        self.delay_between_segments_s = delay_between_segments_s
        self._pos = 0
        self._current = 0
        self._remaining_bits: list[int] = []
        self._next_tick = 0.0

    def Start(self, observer: "SingleTextLineAnimatedObserver", pos: int, char: str) -> bool:
        # Local import to avoid a hard dependency from the base animations
        # package on the led_16 subpackage for observers that never use
        # this animator.
        from .led_16.abstract_led16_animator import AbstractLED16Animator

        self._pos = pos
        self._current = 0
        target = AbstractLED16Animator.get_char_pattern(char)
        self._remaining_bits = [b for b in range(16) if target & (1 << b)]

        seg = observer.DisplayDriver.Seg14x4
        seg.set_digit_raw(pos, 0)
        seg.show()

        if not self._remaining_bits:
            return True  # blank character (e.g. a space) -- nothing to reveal

        self._next_tick = time.monotonic() + self.delay_between_segments_s
        return False

    def Handle(self, observer: "SingleTextLineAnimatedObserver") -> bool:
        if time.monotonic() < self._next_tick:
            return False

        bit = self._remaining_bits.pop(0)
        self._current |= 1 << bit

        seg = observer.DisplayDriver.Seg14x4
        seg.set_digit_raw(self._pos, self._current)
        seg.show()

        if not self._remaining_bits:
            return True

        self._next_tick = time.monotonic() + self.delay_between_segments_s
        return False
