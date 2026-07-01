import logging
import queue
import threading
import time

from panel.panel_input_base import JukeboxPanelInputBase, JukeboxPanelOutputBase
from .observer_base import ObserverBase, UpdateEventType


class Coordinator:
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

        # All update_song_info() calls are marshalled onto this queue so that
        # observer.draw() and observer.UpdateReceived() always run on the same
        # coordinator thread — keeping I2C access single-threaded and avoiding
        # the C-level race that caused the segfault.
        self._event_queue: queue.Queue = queue.Queue()

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

        self.updateJukeboxDisplay()

    def add_observer(self, observer: ObserverBase):
        with self._observers_lock:
            if observer not in self.observers:
                self.observers.append(observer)

    def remove_observer(self, observer: ObserverBase):
        with self._observers_lock:
            if observer in self.observers:
                self.observers.remove(observer)

    def play_ended(self):
        """Thread-safe: enqueue a play_end event to clear the display."""
        self._event_queue.put(('play_end',))

    def update_song_info(self, artist: str, song_title: str):
        """Thread-safe: enqueue updates; the coordinator thread applies them."""
        self._event_queue.put(('song', artist, song_title))

    def shutdown(self, message: str = "Shutting down coordinator"):
        """Thread-safe: enqueue a shutdown sentinel."""
        self._event_queue.put(('shutdown', message))
        self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Internal — runs entirely on the coordinator thread
    # ------------------------------------------------------------------

    def _apply_song_update(self, artist: str, song_title: str):
        self._notify(UpdateEventType.ARTIST, artist)
        self._notify(UpdateEventType.SONG_TITLE, song_title)
        self._updateCount += 1
        self.updateJukeboxDisplay()
        self._timeout = time.monotonic() + Coordinator.TimeoutLimitInSeconds

    def _notify(self, update_type: UpdateEventType, value: str):
        with self._observers_lock:
            snapshot = list(self.observers)
        for observer in snapshot:
            observer.UpdateReceived(update_type=update_type, value=value)

    def _next_wakeup(self) -> float:
        """Compute how long the loop can sleep before the next draw tick is due."""
        deadlines: list[float] = []

        remaining_timeout = self._timeout - time.monotonic()
        if remaining_timeout > 0:
            deadlines.append(remaining_timeout)

        with self._observers_lock:
            snapshot = list(self.observers)
        for observer in snapshot:
            w = observer.next_wakeup()
            if w is not None:
                deadlines.append(w)

        return max(0.0, min(deadlines)) if deadlines else 1.0

    def _loop(self):
        while self.IsRunning:
            sleep_for = self._next_wakeup()

            try:
                item = self._event_queue.get(timeout=sleep_for)
            except queue.Empty:
                item = None

            if item is not None:
                kind = item[0]
                if kind == 'song':
                    _, artist, song_title = item
                    self._apply_song_update(artist, song_title)
                elif kind == 'play_end':
                    self._notify(UpdateEventType.STATE_PLAYBACK_STOPPED, '')
                elif kind == 'shutdown':
                    _, message = item
                    self.IsRunning = False
                    with self._observers_lock:
                        snapshot = list(self.observers)
                    for observer in snapshot:
                        observer.shutdown(message=message)
                    return

            # Check idle timeout
            if time.monotonic() >= self._timeout:
                self._notify(UpdateEventType.NO_EVENT_RECEIVED_TIMEOUT, '')
                self._timeout = time.monotonic() + Coordinator.TimeoutLimitInSeconds

            with self._observers_lock:
                snapshot = list(self.observers)
            for observer in snapshot:
                observer.draw()

    def updateJukeboxDisplay(self):
        x = self._updateCount % 2
        self._panelDisplay.LeftLedSet(x == 1)
        self._panelDisplay.RightLedSet(x == 0)
        self._panelDisplay.WriteToThreeDigitDisplay(str(self._updateCount))
