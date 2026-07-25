import argparse
import time
import threading
import logging

import drivers as ldisp
from animations.abstract_clear_animator import ClearTextBlankLeftToRightAnimator
from animations.abstract_character_reveal_animator import (
    CharacterRevealImmediatelyAnimator,
    SegmentByCharacterRevealAnimator,
)
from config import Config, PanelConfig
from observers import UpdateEventType, Coordinator, SingleTextLineAnimatedObserver, KeyValueTextObserver
from panel.panel_input_base import JukeboxPanelArduinoSerial
from panel.jukebox_panel_linux_ascii import JukeboxPanelLinuxAsciiModule
from panel.jukebox_panel_linux_binary import JukeboxPanelLinuxBinaryModule
from music_app_ssh_worker import MusicAppSSHWorker
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

    if panel_config.name == "Raspberry Pi GPIO Linux Driver":
        device = panel_config.options["device"]
        return JukeboxPanelLinuxAsciiModule(device=device, onButtonPress=onButtonPress)

    if panel_config.name == "Raspberry Pi GPIO Linux Binary Driver":
        device = panel_config.options["device"]
        reveal_tick_s = float(panel_config.options.get("reveal_tick_s", 0.1))
        return JukeboxPanelLinuxBinaryModule(device=device, reveal_tick_s=reveal_tick_s, onButtonPress=onButtonPress)

    raise ValueError(
        f"Unsupported jukeboxPanel driver {panel_config.name!r} in config.ini "
        "(only 'Serial', 'Raspberry Pi GPIO Linux Driver', and "
        "'Raspberry Pi GPIO Linux Binary Driver' are currently implemented)"
    )


_CHARACTER_REVEAL_ANIMATIONS = {
    "immediate": CharacterRevealImmediatelyAnimator,
    "segment": SegmentByCharacterRevealAnimator,
}


def apply_animation_config(observer, config: Config):
    animation_config = config.animation_for_width(observer.DisplayWidth)
    if animation_config.delay_between_characters_s is not None:
        observer.delay_between_characters_s = animation_config.delay_between_characters_s
    if animation_config.delay_after_line_finished_s is not None:
        observer.delay_after_line_finished_s = animation_config.delay_after_line_finished_s
    if animation_config.delay_after_animation_finished_s is not None:
        observer.delay_after_animation_finished_s = animation_config.delay_after_animation_finished_s

    # Defaults to "segment" (SegmentByCharacterRevealAnimator) rather than
    # the class's own instant default -- that's the animation actually
    # wanted here; config.ini can opt individual displays back to
    # "immediate" instead.
    reveal_choice = animation_config.character_reveal_animation or "segment"
    observer.CharacterRevealAnimation = _CHARACTER_REVEAL_ANIMATIONS[reveal_choice]()
    if animation_config.delay_between_segments_s is not None:
        reveal_animation = observer.CharacterRevealAnimation
        if hasattr(reveal_animation, 'delay_between_segments_s'):
            reveal_animation.delay_between_segments_s = animation_config.delay_between_segments_s


def main(config_path=None):
    config = Config(config_path)

    # build_panel() below starts a background thread that can call this
    # immediately -- e.g. the kernel driver's kfifo may already hold a
    # queued press from before this process even started -- which can be
    # well before `coordinator` is assigned a few lines down. Route through
    # this holder instead of closing over `coordinator` directly so a stray
    # early event is dropped rather than crashing (and permanently killing)
    # the read thread with an unbound-variable NameError.
    coordinator_holder = []

    def onPanelButtonPress(key: str):
        if coordinator_holder:
            coordinator_holder[0].on_button_press(key)

    def onTrackSelected(entered: str) -> bool:
        track = playlist.get_by_index(int(entered) - TRACK_INDEX_OFFSET) if playlist is not None else None
        if track is not None:
            source.queue_next(track.persistent_id)
        else:
            logger.info(f"No playlist track matches selection {entered}")
        return track is not None

    def onCommand(command: str) -> None:
        source.send_remote_command(command)

    panel = build_panel(config.panel(), onPanelButtonPress)
    feedback_config = config.track_selection_feedback()
    pause_flash_config = config.playback_pause_flash()
    coordinator = Coordinator(
        panelButtons=panel,
        panelDisplay=panel,
        on_selection_complete=onTrackSelected,
        on_command=onCommand,
        blink_count=feedback_config.blink_count,
        blink_phase_s=feedback_config.blink_phase_s,
        error_text=feedback_config.error_text,
        error_duration_s=feedback_config.error_duration_s,
        flash_interval_s=pause_flash_config.flash_interval_s,
    )
    coordinator_holder.append(coordinator)

    try:
        playlist = Playlist(path=config.playlist_path())
    except Exception as e:
        logger.error(f"Failed to load playlist: {e}")
        coordinator.add_message("Error", "Playlist load failed", ttl_s=0, display_s=5)
        playlist = None

    led_artist_observer = SingleTextLineAnimatedObserver(driver=led0, event_type=UpdateEventType.ARTIST)
    apply_animation_config(led_artist_observer, config)

    led_song_title_observer = SingleTextLineAnimatedObserver(driver=led1, event_type=UpdateEventType.SONG_TITLE)
    led_song_title_observer.ClearDisplayAnimation = ClearTextBlankLeftToRightAnimator()
    apply_animation_config(led_song_title_observer, config)

    kv_observer = KeyValueTextObserver(
        key_driver=led_artist_observer,
        value_driver=led_song_title_observer,
        fields=config.display_fields(),
    )
    coordinator.add_observer(kv_observer)

    def onTrackIdChanged(track_id: str):
        track = None
        if playlist is not None:
            try:
                track = playlist.get_by_persistent_id(track_id)
            except ValueError:
                track = None
        coordinator.display_track_number(
            str(track.index + TRACK_INDEX_OFFSET).rjust(4) if track is not None else '----',
            is_known_track=track is not None,
        )

    # exercise(coordinator)
    mqtt_config = config.mqtt()
    def onConnectionLost():
        coordinator.add_message("Problem", "MQTT Lost. Attempting Reconnect.", ttl_s=0, display_s=5)

    def onConnectionEstablished():
        coordinator.remove_message("Problem")

    def onPlaybackPaused():
        coordinator.set_playback_paused(True)

    def onPlaybackResumed():
        coordinator.set_playback_paused(False)

    def onActiveEnd():
        coordinator.clear_for_inactive()

    def onRemoteCommandUnresponsive():
        # Called from a background thread the MQTT source spawns per
        # command (see ShairportSyncMQTTSource._await_remote_command_ack) --
        # never from the coordinator thread -- so it's safe to let the SSH
        # exec block here without freezing the panel display/keypad.
        if ssh_worker is None:
            return
        try:
            result = ssh_worker.recover_airplay_playback()
            logger.warning(
                "MQTT remote command unresponsive -- ran AirPlay recovery over SSH: %s",
                (result.stdout or result.stderr).strip(),
            )
        except ConnectionError as e:
            logger.warning("MQTT remote command unresponsive, but SSH worker isn't connected: %s", e)

    source = ShairportSyncMQTTSource(
        on_song_changed=coordinator.update_song_info,
        on_play_end=coordinator.play_ended,
        on_track_id_changed=onTrackIdChanged,
        on_connection_lost=onConnectionLost,
        on_connection_established=onConnectionEstablished,
        on_playback_paused=onPlaybackPaused,
        on_playback_resumed=onPlaybackResumed,
        on_active_end=onActiveEnd,
        on_remote_command_unresponsive=onRemoteCommandUnresponsive,
        broker_host=mqtt_config.broker_host,
        broker_port=mqtt_config.broker_port,
        base_topic=mqtt_config.base_topic,
        remote_command_timeout_s=mqtt_config.remote_command_timeout_s,
    )
    source.start()

    ssh_worker_config = config.ssh_worker()
    ssh_worker = None
    if ssh_worker_config is not None:
        ssh_worker = MusicAppSSHWorker(
            host=ssh_worker_config.host,
            username=ssh_worker_config.username,
            key_path=ssh_worker_config.key_path,
            port=ssh_worker_config.port,
            keepalive_interval_s=ssh_worker_config.keepalive_interval_s,
            reconnect_delay_s=ssh_worker_config.reconnect_delay_s,
            connect_timeout_s=ssh_worker_config.connect_timeout_s,
            strict_host_key_checking=ssh_worker_config.strict_host_key_checking,
            airplay_device_name=ssh_worker_config.airplay_device_name,
        )
        ssh_worker.start()

    coordinator.add_message("Weather", "Sunny 72°F", ttl_s=300, display_s=5)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        source.stop()
        if ssh_worker is not None:
            ssh_worker.stop()
        coordinator.shutdown()


if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument(
        '-c', '--config',
        dest='config_path',
        default=None,
        help="Path to the config INI file (default: src/config.ini)",
    )
    args = arg_parser.parse_args()

    formatter = logging.Formatter(
        fmt='%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s',
        datefmt='%M:%S'
    )
    logger = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    main(args.config_path)
