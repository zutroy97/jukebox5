import logging
import queue
import threading
import time
from typing import Callable, Optional

from panel.panel_input_base import JukeboxPanelInputBase, JukeboxPanelOutputBase
from .observer_base import ObserverBase, UpdateEventType


class _TrackSelector:
    """Accumulates digits typed on the panel into a 3-digit track selection.

    Only ever touched from the Coordinator's own thread (via `_enqueue` and
    the `_loop` polling below), so it needs no locking of its own.
    """

    DIGIT_COUNT: int = 3
    SELECTION_TIMEOUT_S: float = 10.0

    def __init__(self, panel_display: JukeboxPanelOutputBase, on_selection_complete: Callable[[str], None]) -> None:
        self._panel_display = panel_display
        self._on_selection_complete = on_selection_complete
        self._digits: str = ""
        self._deadline: Optional[float] = None

    def is_active(self) -> bool:
        return self._deadline is not None

    def button_pressed(self, key: str) -> None:
        if key == 'R':
            self._reset()
            return
        if key not in "0123456789":
            return

        if not self._digits:
            self._panel_display.RightLedSet(True)
        self._digits += key
        self._deadline = time.monotonic() + self.SELECTION_TIMEOUT_S
        self._panel_display.WriteToFourDigitDisplay(self._digits.ljust(4))

        if len(self._digits) < self.DIGIT_COUNT:
            return

        entered = self._digits
        self._reset()
        self._on_selection_complete(entered)

    def next_wakeup(self) -> Optional[float]:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())

    def check_timeout(self) -> None:
        if self._deadline is not None and time.monotonic() >= self._deadline:
            self._reset()

    def _reset(self) -> None:
        self._digits = ""
        self._deadline = None
        self._panel_display.RightLedSet(False)
        self._panel_display.WriteToFourDigitDisplay(' ' * 4)


class Coordinator:
    """Owns the single background thread that all observer I/O runs on.

    Every public method below is thread-safe: it just packages the call as a
    zero-argument closure and drops it on `_event_queue`. The coordinator
    thread (`_loop`) is the only thread that ever calls a closure, notifies
    observers, or draws them — this keeps I2C/serial access single-threaded
    without every caller having to reason about locking.
    """

    TimeoutLimitInSeconds: int = 30 * 60

    def __init__(self, **kwargs) -> None:
        self._logger = logging.getLogger(__class__.__name__)
        self.observers: list[ObserverBase] = []
        self._observers_lock = threading.RLock()
        self.IsRunning: bool = True
        self._timeout: float = time.monotonic() + Coordinator.TimeoutLimitInSeconds
        self._panelButton: JukeboxPanelInputBase = kwargs['panelButtons']
        self._panelDisplay: JukeboxPanelOutputBase = kwargs['panelDisplay']
        self._updateCount: int = 0

        on_selection_complete = kwargs.get('on_selection_complete', lambda entered: None)
        self._track_selector = _TrackSelector(panel_display=self._panelDisplay, on_selection_complete=on_selection_complete)

        self._event_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

        # Marshal the initial display update onto the coordinator thread too,
        # rather than calling it directly here — that would race with the
        # loop thread over the panel display's I2C access.
        self._enqueue(self.updateJukeboxDisplay)

    # ------------------------------------------------------------------
    # Observer management
    # ------------------------------------------------------------------

    def add_observer(self, observer: ObserverBase) -> None:
        with self._observers_lock:
            if observer not in self.observers:
                self.observers.append(observer)

    def remove_observer(self, observer: ObserverBase) -> None:
        with self._observers_lock:
            if observer in self.observers:
                self.observers.remove(observer)

    def _snapshot_observers(self) -> list[ObserverBase]:
        with self._observers_lock:
            return list(self.observers)

    # ------------------------------------------------------------------
    # Public thread-safe API — each call is just packaged as a closure and
    # handed to the coordinator thread.
    # ------------------------------------------------------------------

    def _enqueue(self, task: Callable[[], None]) -> None:
        self._event_queue.put(task)

    def update_song_info(self, artist: str, song_title: str, album: str = "") -> None:
        """Notify observers of a new track."""
        self._enqueue(lambda: self._apply_song_update(artist, song_title, album))

    def play_ended(self) -> None:
        """Notify observers that playback has stopped and the display should clear."""
        self._enqueue(self._apply_play_ended)

    def add_message(self, title: str, text: str, ttl_s: float = 0, display_s: float = 5) -> None:
        """Add or update a custom message in the display rotation.

        Args:
            title:     Unique identifier for the message (shown as the label).
            text:      Message body (shown as the value).
            ttl_s:     Seconds until the message is automatically removed.
                       0 means the message persists until explicitly removed.
            display_s: Seconds the message is held on screen after its animation
                       completes before advancing to the next item in the cycle.
        """
        self._enqueue(lambda: self._apply_message(title, text, ttl_s, display_s))

    # update_message is an alias: adding a message that already exists (by
    # title) replaces it, so there's no separate code path needed.
    update_message = add_message

    def remove_message(self, title: str) -> None:
        """Remove a custom message from the display rotation by title.
        No-op if the message is not present."""
        self._enqueue(lambda: self._apply_message(title, text=None, ttl_s=0, display_s=0))

    def display_track_number(self, text: str) -> None:
        """Write a value to the four-digit panel display."""
        self._enqueue(lambda: self._panelDisplay.WriteToFourDigitDisplay(text))

    def on_button_press(self, key: str) -> None:
        """Feed a raw panel button press ('0'-'9', 'R', 'P') into track selection."""
        self._enqueue(lambda: self._track_selector.button_pressed(key))

    def shutdown(self, message: str = "Shutting down coordinator") -> None:
        """Shut down the coordinator loop cleanly and wait for it to exit."""
        self._enqueue(lambda: self._apply_shutdown(message))
        self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal — runs entirely on the coordinator thread
    # ------------------------------------------------------------------

    def _apply_song_update(self, artist: str, song_title: str, album: str = "") -> None:
        self._notify_all(UpdateEventType.ARTIST, artist)
        if album and album.strip():
            self._notify_all(UpdateEventType.ALBUM, album.strip())
        self._notify_all(UpdateEventType.SONG_TITLE, song_title)
        self._updateCount += 1
        self.updateJukeboxDisplay()
        self._timeout = time.monotonic() + Coordinator.TimeoutLimitInSeconds

    def _apply_play_ended(self) -> None:
        self._notify_all(UpdateEventType.STATE_PLAYBACK_STOPPED, '')
        self._notify_all(UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT, '')

    def _apply_message(self, title: str, text: str | None, ttl_s: float, display_s: float) -> None:
        for observer in self._snapshot_observers():
            observer.UpdateReceived(
                update_type=UpdateEventType.CUSTOM_MESSAGE,
                title=title,
                text=text,
                ttl_s=ttl_s,
                display_s=display_s,
            )

    def _apply_shutdown(self, message: str) -> None:
        self.IsRunning = False
        for observer in self._snapshot_observers():
            observer.shutdown(message=message)

    def _notify_all(self, update_type: UpdateEventType, value: str) -> None:
        for observer in self._snapshot_observers():
            observer.UpdateReceived(update_type=update_type, value=value)

    def _next_wakeup(self) -> float:
        deadlines: list[float] = []

        remaining_timeout = self._timeout - time.monotonic()
        if remaining_timeout > 0:
            deadlines.append(remaining_timeout)

        selection_wakeup = self._track_selector.next_wakeup()
        if selection_wakeup is not None:
            deadlines.append(selection_wakeup)

        for observer in self._snapshot_observers():
            w = observer.next_wakeup()
            if w is not None:
                deadlines.append(w)

        return max(0.0, min(deadlines)) if deadlines else 1.0

    def _loop(self) -> None:
        while self.IsRunning:
            sleep_for = self._next_wakeup()

            try:
                task = self._event_queue.get(timeout=sleep_for)
            except queue.Empty:
                task = None

            if task is not None:
                task()
                if not self.IsRunning:
                    return

            if time.monotonic() >= self._timeout:
                self._notify_all(UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT, '')
                self._timeout = time.monotonic() + Coordinator.TimeoutLimitInSeconds

            self._track_selector.check_timeout()

            for observer in self._snapshot_observers():
                observer.draw()

    def updateJukeboxDisplay(self) -> None:
        x = self._updateCount % 2
        self._panelDisplay.LeftLedSet(x == 1)
        if not self._track_selector.is_active():
            self._panelDisplay.RightLedSet(x == 0)
        self._panelDisplay.WriteToThreeDigitDisplay(str(self._updateCount))
