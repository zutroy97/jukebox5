import logging
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt


class ShairportSyncMQTTSource:
    """Subscribes to shairport-sync MQTT metadata and calls:
        on_song_changed(artist, title, album)  — when a new track starts
        on_play_end()                          — when shairport-sync/play_end is received
        on_track_id_changed(track_id)          — when a new track_id is received

    Artist and title are the priority fields. on_song_changed fires as soon as
    both are known. Album is included if it has already arrived; if it arrives
    later it is ignored (the song is already displaying). track_id is used to
    detect track changes and flush stale metadata.

    Compatible with paho-mqtt 1.x and 2.x.
    """

    RECONNECT_DELAY_S: float = 5.0

    def __init__(
        self,
        on_song_changed: Callable[[str, str, str], None],
        on_play_end: Callable[[], None],
        on_track_id_changed: Optional[Callable[[str], None]] = None,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        base_topic: str = "shairport-sync",
        client_id: str = "jukebox",
    ) -> None:
        self._logger = logging.getLogger(__class__.__name__)
        self._on_song_changed = on_song_changed
        self._on_play_end = on_play_end
        self._on_track_id_changed = on_track_id_changed
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._base_topic = base_topic.rstrip("/")

        self._artist: Optional[str] = None
        self._title: Optional[str] = None
        self._album: Optional[str] = None
        self._track_id: Optional[str] = None
        self._fired: bool = False   # True once on_song_changed has fired for current track
        self._lock = threading.Lock()
        self._running = False

        self._topic_artist   = f"{self._base_topic}/artist"
        self._topic_title    = f"{self._base_topic}/title"
        self._topic_album    = f"{self._base_topic}/album"
        self._topic_track_id = f"{self._base_topic}/track_id"
        self._topic_play_end = f"{self._base_topic}/play_end"

        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id=client_id,
            )
        except AttributeError:
            self._client = mqtt.Client(client_id=client_id)

        self._client.on_connect    = self._on_connect
        self._client.on_message    = self._on_message
        self._client.on_disconnect = self._on_disconnect

    def start(self) -> None:
        self._running = True
        t = threading.Thread(target=self._connect_loop, daemon=True)
        t.start()

    def stop(self) -> None:
        self._running = False
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

    def _connect_loop(self) -> None:
        while self._running:
            try:
                self._logger.info(
                    "Connecting to MQTT broker %s:%d ...",
                    self._broker_host, self._broker_port,
                )
                self._client.connect(self._broker_host, self._broker_port, keepalive=60)
                self._client.loop_forever()
            except Exception as e:
                self._logger.error("MQTT connection error: %s", e)
            if self._running:
                self._logger.info("Reconnecting in %.0fs...", self.RECONNECT_DELAY_S)
                time.sleep(self.RECONNECT_DELAY_S)

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            self._logger.error("MQTT connect refused, rc=%d", rc)
            return
        self._logger.info("MQTT connected")
        client.subscribe([
            (self._topic_artist,   0),
            (self._topic_title,    0),
            (self._topic_album,    0),
            (self._topic_track_id, 0),
            (self._topic_play_end, 0),
        ])

    def _on_disconnect(self, client, userdata, rc):
        self._logger.warning("MQTT disconnected rc=%d", rc)

    def _try_fire(self, artist: Optional[str], title: Optional[str], album: Optional[str]) -> bool:
        """Fire on_song_changed if artist and title are both present.
        Must be called WITHOUT self._lock held (callback may take time).
        Returns True if fired."""
        if artist and title:
            self._logger.info("Song changed: %r — %r (%r)", artist, title, album or "")
            self._on_song_changed(artist, title, album or "")
            return True
        return False

    def _reset_track(self) -> None:
        """Flush all metadata for the current track. Call with self._lock held."""
        self._artist   = None
        self._title    = None
        self._album    = None
        self._fired    = False

    def _on_message(self, client, userdata, msg):
        try:
            value = msg.payload.decode("utf-8").strip()
        except UnicodeDecodeError:
            self._logger.warning("Bad payload on %s", msg.topic)
            return

        self._logger.info("MQTT %-40s %r", msg.topic, value)

        if msg.topic == self._topic_play_end:
            self._logger.info("Play ended — clearing display")
            with self._lock:
                self._reset_track()
                self._track_id = None
            self._on_play_end()
            return

        fire_artist = fire_title = fire_album = None
        fire_track_id = None

        with self._lock:
            if msg.topic == self._topic_track_id:
                if value != self._track_id:
                    self._logger.debug(
                        "New track_id %r (was %r) — resetting metadata",
                        value, self._track_id,
                    )
                    self._reset_track()
                    self._track_id = value
                    fire_track_id = value
            elif msg.topic == self._topic_artist:
                if self._fired:
                    # No track_id reset happened for this track (either the
                    # broker doesn't publish track_id, or it arrived after
                    # this artist message). A fresh artist message after
                    # we've already fired means a new track is starting.
                    self._reset_track()
                self._artist = value

            elif msg.topic == self._topic_title:
                self._title = value

            elif msg.topic == self._topic_album:
                self._album = value
                # Album alone never triggers — artist+title must arrive first.
                return

            # Fire as soon as artist AND title are known, but only once per track.
            if msg.topic != self._topic_track_id and not self._fired and self._artist and self._title:
                self._fired = True
                fire_artist = self._artist
                fire_title  = self._title
                fire_album  = self._album  # may be None if album hasn't arrived yet

        if fire_track_id is not None and self._on_track_id_changed:
            self._on_track_id_changed(fire_track_id)

        if fire_artist:
            self._try_fire(fire_artist, fire_title, fire_album)