import threading
import time
from collections import deque


class RemoteControlSelector:
    """Decides whether a playback remote-control command (playpause/
    nextitem/previtem/an immediate-play track selection) should be sent
    via direct Music.app JXA control or shairport-sync's MQTT/DACP
    remote-control feature, based on the configured mode:

      - "jxa": always JXA.
      - "mqtt": always MQTT/DACP.
      - "fallback": starts on MQTT, permanently switches to JXA once MQTT
        commands have gone unacknowledged (see ShairportSyncMQTTSource.
        send_remote_command()'s docstring for why a missing broker PUBACK
        is the only generic failure signal available) more than
        failure_threshold times within a trailing window_s window. Once
        tripped, stays on JXA for the rest of this process's run -- a
        one-way circuit breaker, not a retry loop, since repeatedly
        re-testing a path already proven unreliable just risks repeating
        the same silent failures it exists to avoid.

    In every mode, main.py's callers still gate on whether [sshWorker] is
    actually configured before honoring should_use_jxa() -- "jxa"/
    "fallback" both degrade to plain MQTT behavior if it isn't, rather
    than erroring.

    Thread-safe: record_mqtt_failure() is called from
    ShairportSyncMQTTSource's own background thread (on_remote_command_
    unresponsive), while should_use_jxa() is read from the coordinator's
    thread.
    """

    _VALID_MODES = ("jxa", "mqtt", "fallback")

    def __init__(self, mode: str, failure_threshold: int, window_s: float) -> None:
        if mode not in self._VALID_MODES:
            raise ValueError(f"Invalid remote_control_mode {mode!r}, must be one of {self._VALID_MODES}")
        self._mode = mode
        self._failure_threshold = failure_threshold
        self._window_s = window_s
        self._lock = threading.Lock()
        self._failure_times: deque = deque()
        self._tripped = False

    def should_use_jxa(self) -> bool:
        if self._mode == "jxa":
            return True
        if self._mode == "mqtt":
            return False
        with self._lock:
            return self._tripped

    def record_mqtt_failure(self) -> None:
        """Call whenever an MQTT remote-control command goes unacknowledged.
        No-op outside "fallback" mode, and once already tripped -- past
        that point there is nothing left for another failure to change."""
        if self._mode != "fallback":
            return
        now = time.monotonic()
        with self._lock:
            if self._tripped:
                return
            self._failure_times.append(now)
            cutoff = now - self._window_s
            while self._failure_times and self._failure_times[0] < cutoff:
                self._failure_times.popleft()
            if len(self._failure_times) > self._failure_threshold:
                self._tripped = True
