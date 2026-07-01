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
    """Cycles through artist, title, and album (if present) on two displays:
        key_driver   (8-char)  — label:  'Artist', 'Title', or 'Album'
        value_driver (12-char) — value:  the corresponding metadata value

    The between-pair pause uses key_driver.delay_after_animation_finished_s.
    Album is only included in the cycle when non-empty.
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
        self._album: str = ""
        self._cycle: list[tuple[str, str]] = []
        self._kv_state: _State = _State.IDLE
        self._pause_until: float = 0.0

    @property
    def _between_pair_delay_s(self) -> float:
        return self._key_driver.delay_after_animation_finished_s

    def _build_cycle(self) -> list[tuple[str, str]]:
        self._purge_expired_messages()
        cycle: list[tuple[str, str]] = []
        if self._artist or self._song_title:
            cycle.append(("Artist", self._artist))
            cycle.append(("Title", self._song_title))
            if self._album:
                cycle.append(("Album", self._album))
        cycle.extend((m.title, m.text) for m in self._message_rotation)
        return cycle

    def _show_pair(self, label: str, value: str) -> None:
        self._key_driver.Value = label
        self._value_driver.Value = value
        self._kv_state = _State.ANIMATING

    def _update_cycle_entry(self, label: str, value: str) -> None:
        """Update an existing cycle entry in place, or append if not present.
        If value is empty or whitespace, remove the entry from the cycle."""
        value = value.strip() if value else ""
        if not value:
            self._cycle = [(l, v) for l, v in self._cycle if l != label]
            return
        for i, (lbl, _) in enumerate(self._cycle):
            if lbl == label:
                self._cycle[i] = (label, value)
                return
        self._cycle.append((label, value))

    def next_wakeup(self) -> Optional[float]:
        if self._kv_state == _State.PAUSING:
            # Once the pause window elapses we must wake up immediately to
            # advance to the next pair — the key/value drivers are idle at
            # this point (auto_loop=False) and would otherwise report no
            # wakeup needed, stalling the rotation until an unrelated event
            # wakes the coordinator.
            remaining = self._pause_until - time.monotonic()
            return max(0.0, remaining)
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
            if not self._cycle:
                # Nothing left to show (e.g. the last rotation message expired
                # with no song playing) — go idle until something new arrives.
                self._go_idle_or_resume_messages()
                self._key_driver._driver.clear()
                self._value_driver._driver.clear()
                return
            label, value = self._cycle.pop(0)
            self._show_pair(label, value)

        self._key_driver.draw()
        self._value_driver.draw()

        if (self._kv_state == _State.ANIMATING
                and self._key_driver._state in _FINISHED_STATES
                and self._value_driver._state in _FINISHED_STATES):
            self._kv_state = _State.PAUSING
            self._pause_until = time.monotonic() + self._between_pair_delay_s

    def _go_idle_or_resume_messages(self) -> None:
        """Go idle, unless there are still active rotation messages to show —
        in that case resume the cycle immediately instead of waiting for a
        song to start it back up."""
        self._purge_expired_messages()
        self._cycle = []
        if self._message_rotation:
            self._kv_state = _State.PAUSING
            self._pause_until = time.monotonic()
        else:
            self._kv_state = _State.IDLE

    def on_messages_changed(self) -> None:
        # A message was added/updated while nothing was playing — kick the
        # rotation out of IDLE so it shows on the next draw() instead of
        # waiting for a song to start.
        if self._kv_state == _State.IDLE:
            self._go_idle_or_resume_messages()

    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        self._purge_expired_messages()

        if update_type == UpdateEventType.CUSTOM_MESSAGE:
            self._handle_message(**kwargs)
            return

        if update_type == UpdateEventType.ARTIST:
            self._artist = kwargs.get('value', self._artist)
            # Clear album — a new track is starting and album hasn't arrived yet.
            # If an ALBUM event follows it will be added to the cycle then.
            self._album = ""
            # Interrupt immediately with artist; queue title after.
            # Album is intentionally excluded here — it will be appended
            # when UpdateEventType.ALBUM arrives, if at all.
            self._cycle = [("Title", self._song_title)]
            self._show_pair("Artist", self._artist)

        elif update_type == UpdateEventType.SONG_TITLE:
            self._song_title = kwargs.get('value', self._song_title)
            self._update_cycle_entry("Title", self._song_title)

        elif update_type == UpdateEventType.ALBUM:
            self._album = (kwargs.get('value', self._album) or '').strip()
            self._update_cycle_entry("Album", self._album)

        elif update_type == UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT:
            self.timeout_expired()

        elif update_type == UpdateEventType.STATE_PLAYBACK_STOPPED:
            self._clear_display_and_stop_animation()

    def timeout_expired(self) -> None:
        """Called on play_end — clear both displays and return to idle,
        resuming the message rotation if any messages are still active."""
        self._artist = ""
        self._song_title = ""
        self._album = ""
        self._go_idle_or_resume_messages()
        self._key_driver._driver.clear()
        self._value_driver._driver.clear()

    def _clear_display_and_stop_animation(self) -> None:
        self._artist = ""
        self._song_title = ""
        self._album = ""
        self._go_idle_or_resume_messages()
        self._key_driver._driver.clear()
        self._value_driver._driver.clear()
