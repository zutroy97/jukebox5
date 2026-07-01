from enum import Enum, auto
from typing import Optional
import time

from ..observer_base import UpdateEventType, ObserverBase
from .single_text_line_animated import SingleTextLineAnimatedObserver
from observers.observer_states import ObserverStates

_FINISHED_STATES = frozenset([ObserverStates.ANIMATION_FINISHED, ObserverStates.IDLE])


class _State(Enum):
    ANIMATING = auto()
    PAUSING   = auto()
    IDLE      = auto()


class KeyValueTextObserver(ObserverBase):
    """Cycles through artist and title on two displays:
        key_driver   (8-char)  — label:  'Artist' or 'Title'
        value_driver (12-char) — value:  artist name or song title

    The between-pair pause uses key_driver.delay_after_animation_finished_s
    so there is a single place to tune all timing.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__()
        if "key_driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'key_driver'")
        self._key_driver: SingleTextLineAnimatedObserver = kwargs['key_driver']
        self._key_driver.auto_loop = False

        if "value_driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'value_driver'")
        self._value_driver: SingleTextLineAnimatedObserver = kwargs['value_driver']
        self._value_driver.auto_loop = False

        self._artist: str = ""
        self._song_title: str = ""
        self._cycle: list[tuple[str, str]] = []
        self._kv_state: _State = _State.IDLE
        self._pause_until: float = 0.0

    @property
    def _between_pair_delay_s(self) -> float:
        return self._key_driver.delay_after_animation_finished_s

    def _build_cycle(self) -> list[tuple[str, str]]:
        return [("Artist", self._artist), ("Title", self._song_title)]

    def _show_pair(self, label: str, value: str) -> None:
        self._key_driver.Value = label
        self._value_driver.Value = value
        self._kv_state = _State.ANIMATING

    def next_wakeup(self) -> Optional[float]:
        if self._kv_state == _State.PAUSING:
            remaining = self._pause_until - time.monotonic()
            if remaining > 0:
                return remaining
        key_wake = self._key_driver.next_wakeup()
        val_wake = self._value_driver.next_wakeup()
        candidates = [t for t in (key_wake, val_wake) if t is not None]
        return min(candidates) if candidates else None

    def draw(self) -> None:
        if self._kv_state == _State.IDLE:
            return

        if self._kv_state == _State.PAUSING:
            if time.monotonic() < self._pause_until:
                return
            if not self._cycle:
                self._cycle = self._build_cycle()
            label, value = self._cycle.pop(0)
            self._show_pair(label, value)

        self._key_driver.draw()
        self._value_driver.draw()

        if (self._kv_state == _State.ANIMATING
                and self._key_driver._state in _FINISHED_STATES
                and self._value_driver._state in _FINISHED_STATES):
            self._kv_state = _State.PAUSING
            self._pause_until = time.monotonic() + self._between_pair_delay_s

    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        if update_type == UpdateEventType.ARTIST:
            self._artist = kwargs.get('value', self._artist)
            self._cycle = [("Title", self._song_title)]
            self._show_pair("Artist", self._artist)

        elif update_type == UpdateEventType.SONG_TITLE:
            self._song_title = kwargs.get('value', self._song_title)
            for i, (label, _) in enumerate(self._cycle):
                if label == "Title":
                    self._cycle[i] = ("Title", self._song_title)
                    return
            self._cycle.append(("Title", self._song_title))

        elif update_type == UpdateEventType.STATE_PLAYBACK_STOPPED:
            self._clear_display_and_stop_animation()


    def timeout_expired(self) -> None:
        """Called on play_end — clear both displays and return to idle."""
        self._artist = ""
        self._song_title = ""
        self._cycle = []
        self._kv_state = _State.IDLE
        self._key_driver._driver.clear()
        self._value_driver._driver.clear()

    def _clear_display_and_stop_animation(self) -> None:
        self._artist = ""
        self._song_title = ""
        self._cycle = []
        self._kv_state = _State.IDLE
        self._key_driver._driver.clear()
        self._value_driver._driver.clear()