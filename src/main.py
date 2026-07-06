import time
import threading
import logging

import drivers as ldisp
from animations import RandomTypeWriter
from animations.abstract_clear_animator import ClearTextBlankLeftToRightAnimator
from config import Config, PanelConfig
from observers import UpdateEventType, Coordinator, SingleTextLineAnimatedObserver, KeyValueTextObserver
from panel.panel_input_base import JukeboxPanelArduinoSerial
from playlist import Playlist
from shairport_mqtt import ShairportSyncMQTTSource

from serial import Serial


TRACK_INDEX_OFFSET = 100

led0 = ldisp.led16_display(addr=(0x70, 0x71))
led1 = ldisp.led16_display(addr=(0x72, 0x73, 0x74))


def build_panel(panel_config: PanelConfig, onButtonPress):
    if panel_config.name == "Serial":
        port = panel_config.options["port"]
        baud = int(panel_config.options.get("baud", 115200))
        panelSerial = Serial(port=port, baudrate=baud, timeout=None)
        return JukeboxPanelArduinoSerial(port=panelSerial, onButtonPress=onButtonPress)

    raise ValueError(
        f"Unsupported jukeboxPanel driver {panel_config.name!r} in config.ini "
        "(only 'Serial' is currently implemented)"
    )


def apply_animation_config(observer, config: Config):
    animation_config = config.animation_for_width(observer.DisplayWidth)
    if animation_config.delay_between_characters_s is not None:
        observer.delay_between_characters_s = animation_config.delay_between_characters_s
    if animation_config.delay_after_line_finished_s is not None:
        observer.delay_after_line_finished_s = animation_config.delay_after_line_finished_s
    if animation_config.delay_after_animation_finished_s is not None:
        observer.delay_after_animation_finished_s = animation_config.delay_after_animation_finished_s


def main():
    config = Config()

    def onPanelButtonPress(key: str):
        coordinator.on_button_press(key)

    def onTrackSelected(entered: str):
        track = playlist.get_by_index(int(entered) - TRACK_INDEX_OFFSET) if playlist is not None else None
        if track is not None:
            source.queue_next(track.persistent_id)
        else:
            logger.info(f"No playlist track matches selection {entered}")

    panel = build_panel(config.panel(), onPanelButtonPress)
    coordinator = Coordinator(panelButtons=panel, panelDisplay=panel, on_selection_complete=onTrackSelected)

    try:
        playlist = Playlist(path=config.playlist_path())
    except Exception as e:
        logger.error(f"Failed to load playlist: {e}")
        coordinator.add_message("Error", "Playlist load failed", ttl_s=0, display_s=5)
        playlist = None

    led_artist_observer = SingleTextLineAnimatedObserver(driver=led0, event_type=UpdateEventType.ARTIST)
    apply_animation_config(led_artist_observer, config)

    led_song_title_observer = SingleTextLineAnimatedObserver(driver=led1, event_type=UpdateEventType.SONG_TITLE)
    apply_animation_config(led_song_title_observer, config)
    led_song_title_observer.changeAnimation(RandomTypeWriter())
    led_song_title_observer.ClearDisplayAnimation = ClearTextBlankLeftToRightAnimator()

    kv_observer = KeyValueTextObserver(key_driver=led_artist_observer, value_driver=led_song_title_observer)
    coordinator.add_observer(kv_observer)

    def onTrackIdChanged(track_id: str):
        track = None
        if playlist is not None:
            try:
                track = playlist.get_by_persistent_id(track_id)
            except ValueError:
                track = None
        coordinator.display_track_number(str(track.index + TRACK_INDEX_OFFSET).rjust(4) if track is not None else '----')

    # exercise(coordinator)
    mqtt_config = config.mqtt()
    source = ShairportSyncMQTTSource(
        on_song_changed=coordinator.update_song_info,
        on_play_end=coordinator.play_ended,
        on_track_id_changed=onTrackIdChanged,
        broker_host=mqtt_config.broker_host,
        broker_port=mqtt_config.broker_port,
        base_topic=mqtt_config.base_topic,
    )
    source.start()

    coordinator.add_message("Weather", "Sunny 72°F", ttl_s=300, display_s=5)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        source.stop()
        coordinator.shutdown()


if __name__ == '__main__':
    formatter = logging.Formatter(
        fmt='%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s',
        datefmt='%M:%S'
    )
    logger = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    main()
