import logging
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt


class ShairportSyncMQTTSource:
    """Subscribes to shairport-sync MQTT metadata and calls:
        on_song_changed(artist, title)  — when a new track starts
        on_play_end()                   — when shairport-sync/play_end is received

    Compatible with paho-mqtt 1.x and 2.x.
    """

    RECONNECT_DELAY_S: float = 5.0

    def __init__(
        self,
        on_song_changed: Callable[[str, str], None],
        on_play_end: Callable[[], None],
        broker_host: str = "jukebox4",
        broker_port: int = 1883,
        base_topic: str = "shairport-sync",
        client_id: str = "jukebox",
    ) -> None:
        self._logger = logging.getLogger(__class__.__name__)
        self._on_song_changed = on_song_changed
        self._on_play_end = on_play_end
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._base_topic = base_topic.rstrip("/")
        self._artist: Optional[str] = None
        self._title: Optional[str] = None
        self._lock = threading.Lock()
        self._running = False

        self._topic_artist   = f"{self._base_topic}/artist"
        self._topic_title    = f"{self._base_topic}/title"
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
            (self._topic_play_end, 0),
        ])

    def _on_disconnect(self, client, userdata, rc):
        self._logger.warning("MQTT disconnected rc=%d", rc)

    def _on_message(self, client, userdata, msg):
        try:
            value = msg.payload.decode("utf-8").strip()
        except UnicodeDecodeError:
            self._logger.warning("Bad payload on %s", msg.topic)
            return

        self._logger.info("MQTT %-40s %r", msg.topic, value)

        # TODO: Add handler for shairport-sync/track_id and shairport-sync/album
        if msg.topic == self._topic_play_end:
            self._logger.info("Play ended — clearing display")
            with self._lock:
                self._artist = None
                self._title  = None
            self._on_play_end()
            return

        with self._lock:
            if msg.topic == self._topic_artist:
                self._artist = value
                self._title  = None  # reset: new track arriving
            elif msg.topic == self._topic_title:
                self._title = value
            artist = self._artist
            title  = self._title

        if artist and title:
            self._logger.info("Song changed: %r — %r", artist, title)
            self._on_song_changed(artist, title)