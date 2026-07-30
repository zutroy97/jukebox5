import argparse
import json
import signal
import socket
import sys
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
from music_app_ssh_worker import MusicAppSSHWorker, SUCCESS_OUTPUT
from playlist import Playlist
from remote_control_selector import RemoteControlSelector
from shairport_mqtt import ShairportSyncMQTTSource

from serial import Serial


TRACK_INDEX_OFFSET = 100

# Selecting a number in this range plays that track immediately (direct
# Music.app control via play_track.js when [sshWorker] is configured,
# otherwise a queue_next + "nextitem" remote command pair over MQTT/DACP)
# rather than just queuing it up behind whatever's currently playing --
# its own offset into the playlist, independent of TRACK_INDEX_OFFSET above.
IMMEDIATE_PLAY_RANGE = range(300, 501)
IMMEDIATE_PLAY_INDEX_OFFSET = 300

# How long the Pi's IP address stays in the display rotation after P911.
SHOW_IP_ADDRESS_TTL_S = 30.0

# How long to wait for some sign of active shairport-sync playback (a
# song-changed or play_resume event) before concluding nothing is playing.
# Used both at startup (before running the AirPlay recovery script) and
# after an active_end event (before asking the Mac directly whether
# there's actually a track playing shairport-sync just didn't announce --
# see onActiveEnd/fetchNowPlayingFromMac).
NOTHING_PLAYING_GRACE_S = 5.0

# Feedback shown on the 4-digit panel display (and alpha display, via the
# "Playlist" message) when a track-selection code is entered before the
# playlist has been fetched from the Mac -- distinct from the standard
# error_text/error_duration_s shown when the playlist loaded fine but the
# code just doesn't match any track. See onTrackSelected/loadPlaylistFromMac.
NO_PLAYLIST_PANEL_TEXT = "----"
NO_PLAYLIST_FEEDBACK_DURATION_S = 5.0

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


def main(config: Config):
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

    def runMusicAppCommandAsync(description: str, fn) -> None:
        """Runs a MusicAppSSHWorker call (playpause/next_track/
        previous_track/play_track) on a background thread -- the caller is
        always the coordinator's own single processing thread, which must
        never block on an SSH round-trip -- and logs a warning if it
        didn't cleanly succeed. fn takes no arguments and returns a
        CommandResult; description is just for the log message."""
        def run():
            try:
                result = fn()
                output = (result.stdout or result.stderr).strip()
                if not (result.ok and output == SUCCESS_OUTPUT):
                    logger.warning("%s failed: %s", description, output)
            except ConnectionError as e:
                logger.warning("%s failed: %s", description, e)
        threading.Thread(target=run, daemon=True).start()

    def onTrackSelected(entered: str) -> bool:
        if playlist is None:
            coordinator.add_message(
                "Playlist", "no playlist from mac",
                ttl_s=NO_PLAYLIST_FEEDBACK_DURATION_S, display_s=NO_PLAYLIST_FEEDBACK_DURATION_S,
            )
            return False
        number = int(entered)
        immediate = number in IMMEDIATE_PLAY_RANGE
        offset = IMMEDIATE_PLAY_INDEX_OFFSET if immediate else TRACK_INDEX_OFFSET
        track = playlist.get_by_index(number - offset)
        if track is None:
            logger.info(f"No playlist track matches selection {entered}")
            return False
        if immediate and ssh_worker is not None and remote_control_selector.should_use_jxa():
            # Direct Music.app control -- see play_track.js's comment for
            # why this only covers the immediate case; "queue behind the
            # current track" below still needs shairport-sync's own
            # DACP queue_next, which has no Music.app scripting equivalent
            # (and isn't affected by remote_control_selector's mode at all,
            # for the same reason).
            persistent_id = track.persistent_id
            runMusicAppCommandAsync(
                f"play_track {persistent_id!r} via direct Music.app control",
                lambda: ssh_worker.play_track(persistent_id),
            )
        else:
            # queue_next's <track_id> argument is documented (shairport-sync's
            # development-branch mqtt.c) as "the hex track_id string as
            # published by shairport-sync itself". Whether that needs
            # byte-reversing from track.persistent_id (JXA's format) is NOT
            # fixed -- confirmed empirically to depend on the shairport-sync
            # build (see playlist.get_by_shairport_sync_track_id()'s
            # docstring): the build originally installed needed reversal,
            # the development-branch rebuild done for this same queue_next
            # command did not, on the exact same tracks. Sending the raw,
            # unreversed ID to match the currently-running build; if
            # queue_next starts silently referencing the wrong track after
            # a future shairport-sync rebuild, re-diagnose by comparing
            # Music.currentTrack().persistentID() (get_now_playing.js)
            # against the /track_id MQTT metadata for the same track, the
            # same way this was first found.
            source.queue_next(track.persistent_id)
            if immediate:
                source.send_remote_command("nextitem")
        return True

    def getLocalIpAddress() -> str:
        # Connecting a UDP socket never actually sends a packet -- it just
        # makes the kernel pick a route/local address for that destination
        # -- so this works to find the Pi's own LAN IP even with no real
        # connectivity to 8.8.8.8 (or the internet at all).
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
            except OSError:
                return "no network"

    def showIpAddress() -> None:
        coordinator.add_message(
            "IP", getLocalIpAddress(), ttl_s=SHOW_IP_ADDRESS_TTL_S, display_s=5,
        )

    # Direct Music.app control for these three, as an alternative to
    # shairport-sync's MQTT/DACP remote-control path: DACP has no
    # acknowledgment of whether a command actually took effect (see
    # ShairportSyncMQTTSource.send_remote_command()'s docstring), and was
    # observed silently failing during the Pi Zero port bring-up even with
    # a live AirPlay session. Which path is actually used for a given
    # command is decided by remote_control_selector -- see
    # RemoteControlSelector and mqtt_config.remote_control_mode. Falls
    # back to the MQTT/DACP path regardless of mode if [sshWorker] isn't
    # configured at all.
    DIRECT_COMMAND_FNS = {
        "playpause": lambda: ssh_worker.playpause(),
        "nextitem": lambda: ssh_worker.next_track(),
        "previtem": lambda: ssh_worker.previous_track(),
    }

    def onCommand(command: str) -> None:
        # Local pseudo-commands (see coordinator.py's COMMANDS) -- handled
        # here instead of being forwarded to the Mac, which wouldn't
        # recognize them.
        if command == "advance_display":
            coordinator.advance_display()
            return
        if command == "show_ip_address":
            showIpAddress()
            return

        direct_fn = DIRECT_COMMAND_FNS.get(command)
        used_jxa = ssh_worker is not None and direct_fn is not None and remote_control_selector.should_use_jxa()
        if used_jxa:
            runMusicAppCommandAsync(f"{command!r} via direct Music.app control", direct_fn)
        else:
            source.send_remote_command(command)

        if command == "playpause":
            observed_generation = playback_event_generation[0]

            def checkPlaypauseEffect():
                if playback_event_generation[0] == observed_generation:
                    if not used_jxa:
                        # Counts toward remote_control_selector's fallback
                        # trip (a no-op outside "fallback" mode). This is
                        # the real-world MQTT/DACP failure mode, confirmed
                        # directly: a broker PUBACK (what
                        # onRemoteCommandUnresponsive tracks) only confirms
                        # the message was published, not that DACP actually
                        # did anything on the Mac -- a real playpause
                        # published successfully and still had no effect.
                        remote_control_selector.record_mqtt_failure()
                    runAirplayRecovery("playpause had no effect")

            threading.Timer(mqtt_config.remote_command_timeout_s, checkPlaypauseEffect).start()

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
        get_invalid_feedback=lambda: (
            (NO_PLAYLIST_PANEL_TEXT, NO_PLAYLIST_FEEDBACK_DURATION_S) if playlist is None else None
        ),
    )
    coordinator_holder.append(coordinator)

    # Fetched from the Mac over SSH once it connects (see loadPlaylistFromMac
    # below) rather than loaded from a bundled file -- the Pi's filesystem is
    # read-only, so there's no way to keep a local copy in sync with the
    # Mac's actual "Jukebox" playlist. None until that first fetch succeeds;
    # onTrackSelected/onTrackIdChanged already treat that as "no match".
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
                track = playlist.get_by_shairport_sync_track_id(track_id)
            except ValueError:
                track = None
        coordinator.display_track_number(
            str(track.index + TRACK_INDEX_OFFSET).rjust(4) if track is not None else '----',
            is_known_track=track is not None,
        )

    # exercise(coordinator)
    mqtt_config = config.mqtt()
    remote_control_selector = RemoteControlSelector(
        mode=mqtt_config.remote_control_mode,
        failure_threshold=mqtt_config.remote_control_fallback_threshold,
        window_s=mqtt_config.remote_control_fallback_window_s,
    )
    def onConnectionLost():
        coordinator.add_message("Problem", "MQTT Lost. Attempting Reconnect.", ttl_s=0, display_s=5)

    def onConnectionEstablished():
        coordinator.remove_message("Problem")

    # Bumped on every play_flush/play_resume MQTT message -- the only
    # observable proof shairport-sync actually reacted to something,
    # since its remote-control feature has no per-command ack of its own.
    # onCommand's playpause-effect check below compares against this to
    # tell "shairport-sync paused/resumed" apart from "nothing happened".
    playback_event_generation = [0]

    def onPlaybackPaused():
        playback_event_generation[0] += 1
        coordinator.set_playback_paused(True)

    def onPlaybackResumed():
        playback_event_generation[0] += 1
        coordinator.set_playback_paused(False)

    def onActiveEnd():
        coordinator.clear_for_inactive()
        # A session can end and immediately resume the *same* track (e.g.
        # shairport-sync itself restarting mid-track, as opposed to
        # playback genuinely stopping) -- shairport-sync has no new
        # artist/title/track_id to publish for that, since as far as its
        # own metadata stream is concerned no track boundary was crossed,
        # so the display would otherwise stay blank indefinitely even
        # though audio is streaming again. Check once, after the grace
        # period, whether shairport-sync told us anything on its own in
        # the meantime (playback_event_generation covers pause/resume/song
        # changes); if not, ask the Mac directly -- same fallback startup
        # already uses, just read-only here (no recovery script) since
        # active_end is a normal, frequent event and most of the time
        # nothing actually is playing.
        observed_generation = playback_event_generation[0]

        def checkResumedWithoutMetadata():
            if playback_event_generation[0] != observed_generation:
                return
            fetchNowPlayingFromMac()

        threading.Timer(NOTHING_PLAYING_GRACE_S, checkResumedWithoutMetadata).start()

    def runAirplayRecovery(reason: str) -> None:
        # Callers all run this off the coordinator thread already (a
        # background thread the MQTT source spawns per remote command, or
        # the startup grace-period timer below), so it's safe to block here
        # -- both on the SSH exec(s)/retry sleeps and on showing/removing
        # status messages, which are just another thread-safe coordinator
        # call -- without freezing the panel display/keypad.
        if ssh_worker is None:
            return
        attempts = ssh_worker_config.recovery_attempts
        retry_delay_s = ssh_worker_config.recovery_retry_delay_s
        for attempt in range(1, attempts + 1):
            status = "connecting to mac" if attempts == 1 else f"connecting to mac ({attempt}/{attempts})"
            coordinator.add_message("Status", status, ttl_s=0, display_s=5)
            try:
                result = ssh_worker.recover_airplay_playback()
                output = (result.stdout or result.stderr).strip()
                logger.warning(
                    "%s -- ran AirPlay recovery over SSH (attempt %d/%d): %s",
                    reason, attempt, attempts, output,
                )
                # osascript's exit status is 0 either way here (the script
                # only ever throws for a scripting error, not a "device not
                # found"/"not available" outcome) -- SUCCESS_OUTPUT is the
                # only way to tell success from a handled failure.
                if result.ok and output == SUCCESS_OUTPUT:
                    coordinator.remove_message("Error")
                    return
            except ConnectionError as e:
                logger.warning(
                    "%s, but SSH worker isn't connected (attempt %d/%d): %s",
                    reason, attempt, attempts, e,
                )
            finally:
                coordinator.remove_message("Status")
            if attempt < attempts:
                time.sleep(retry_delay_s)

        coordinator.add_message("Error", "Mac connection failed", ttl_s=0, display_s=5)

    def onRemoteCommandUnresponsive():
        # Counts toward remote_control_selector's fallback trip (a no-op
        # outside "fallback" mode) independently of runAirplayRecovery
        # below -- one tracks whether MQTT itself is reliable enough to
        # keep using, the other tries to fix the AirPlay session itself.
        remote_control_selector.record_mqtt_failure()
        runAirplayRecovery("MQTT remote command unresponsive")

    # Set as soon as there's any sign of an already-active shairport-sync
    # session, so the startup check below can tell "nothing playing" apart
    # from "haven't heard from shairport-sync yet".
    startup_playback_seen = [False]
    startup_check_scheduled = [False]

    def onSongChanged(artist: str, song_title: str, album: str = "") -> None:
        startup_playback_seen[0] = True
        playback_event_generation[0] += 1
        coordinator.remove_message("Error")
        coordinator.update_song_info(artist, song_title, album)

    def onPlaybackResumedWithStartupTracking():
        startup_playback_seen[0] = True
        coordinator.remove_message("Error")
        onPlaybackResumed()

    def fetchNowPlayingFromMac() -> bool:
        """Fallback for a track that's playing on the Mac without
        shairport-sync having told us: it only publishes artist/title/
        album/track_id once, at track start, with no retained message a
        late/resumed MQTT subscription can catch up on -- so a track
        already mid-playback (at this process's own startup, or after
        shairport-sync's session restarts mid-track -- see
        checkStartupPlayback/onActiveEnd) stays invisible on the display
        until the *next* track change, even though playback itself never
        stopped. Ask the Mac directly instead.

        Returns True only if a currently-playing track was found AND this
        Pi's own AirPlay device is confirmed selected there -- Music.app
        reporting playerState "playing" alone is not enough: it could be
        playing to a completely different output while this jukebox has no
        AirPlay session at all (confirmed as a real gap during the Pi Zero
        port bring-up -- checkStartupPlayback below was skipping recovery
        just because *something* was playing on the Mac). The display is
        still updated cosmetically from whatever's playing either way,
        since callers that ignore the return value (see onActiveEnd) want
        that regardless."""
        if ssh_worker is None:
            return False
        try:
            result = ssh_worker.get_now_playing()
        except ConnectionError as e:
            logger.warning("Could not query now-playing track over SSH: %s", e)
            return False
        if not result.ok:
            logger.warning("get_now_playing.js failed: %s", (result.stdout or result.stderr).strip())
            return False
        try:
            info = json.loads(result.stdout)
        except ValueError:
            logger.warning("get_now_playing.js returned unparseable output: %r", result.stdout)
            return False

        if info.get("playerState") != "playing":
            return False
        artist = info.get("artist") or ""
        title = info.get("name") or ""
        if not (artist and title):
            return False

        logger.warning("Found already-playing track via SSH: %r -- %r", artist, title)
        persistent_id = info.get("persistentID")
        if persistent_id:
            onTrackIdChanged(persistent_id.upper())
        onSongChanged(artist, title, info.get("album") or "")
        return bool(info.get("airplaySelected"))

    def checkStartupPlayback():
        if startup_playback_seen[0]:
            return
        if fetchNowPlayingFromMac():
            return
        runAirplayRecovery("Nothing playing via shairport-sync at startup")

    def onConnectionEstablishedThenScheduleStartupCheck():
        onConnectionEstablished()
        if not startup_check_scheduled[0]:
            startup_check_scheduled[0] = True
            threading.Timer(NOTHING_PLAYING_GRACE_S, checkStartupPlayback).start()

    source = ShairportSyncMQTTSource(
        on_song_changed=onSongChanged,
        on_play_end=coordinator.play_ended,
        on_track_id_changed=onTrackIdChanged,
        on_connection_lost=onConnectionLost,
        on_connection_established=onConnectionEstablishedThenScheduleStartupCheck,
        on_playback_paused=onPlaybackPaused,
        on_playback_resumed=onPlaybackResumedWithStartupTracking,
        on_active_end=onActiveEnd,
        on_remote_command_unresponsive=onRemoteCommandUnresponsive,
        broker_host=mqtt_config.broker_host,
        broker_port=mqtt_config.broker_port,
        base_topic=mqtt_config.base_topic,
        remote_command_timeout_s=mqtt_config.remote_command_timeout_s,
    )
    source.start()

    def loadPlaylistFromMac() -> None:
        # Guarded by "already loaded" rather than "already attempted": a
        # transient failure on this (the first) connection should still be
        # retried on the next reconnect, but once a fetch actually
        # succeeds, later reconnects leave it alone -- matches
        # sshWorker.playlist_name's "fetch once per process" semantics
        # without a separate one-shot flag. Runs on the SSH worker's own
        # background connect-loop thread, so blocking here for the several
        # seconds a full playlist enumeration can take is safe -- same
        # reasoning already documented for runAirplayRecovery/
        # fetchNowPlayingFromMac.
        nonlocal playlist
        if playlist is not None:
            return
        try:
            result = ssh_worker.get_playlist_tracks()
        except ConnectionError as e:
            logger.error("Could not load playlist over SSH: %s", e)
            return
        if not result.ok:
            logger.error("get_playlist_tracks.js failed: %s", (result.stdout or result.stderr).strip())
            return
        try:
            raw_tracks = json.loads(result.stdout)
        except ValueError:
            logger.error("get_playlist_tracks.js returned unparseable output: %r", result.stdout)
            return
        playlist = Playlist(raw_tracks)
        logger.info("Loaded %d playlist track(s) from the Mac", len(playlist))

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
            playlist_name=ssh_worker_config.playlist_name,
            on_connection_established=loadPlaylistFromMac,
        )
        ssh_worker.start()

    def performShutdown() -> None:
        """Stops all background workers, then leaves the two alphanumeric
        displays showing the configured shutdown text and the physical
        panel fully unlit -- so anyone looking at the jukebox after
        `systemctl stop`/SIGTERM (or Ctrl+C during development) sees a
        clean "off" state rather than whatever was on screen at the
        moment it died."""
        source.stop()
        if ssh_worker is not None:
            ssh_worker.stop()
        coordinator.shutdown()
        panel.Off()
        shutdown_display = config.shutdown_display()
        # coordinator.shutdown() only *requests* each observer clear its
        # display (an async state-machine transition normally applied on
        # the next observer.draw() -- see Coordinator._loop, which exits
        # immediately after the shutdown task runs and never reaches that
        # draw() call). So the driver-level clear() below is not
        # redundant -- it's the only thing that actually blanks the
        # display and resets the write cursor to 0 before the shutdown
        # text goes up; skipping it left stale characters (and a
        # leftover cursor position) mixed in with the new text.
        led0.clear()
        led0.write(shutdown_display.alpha_text)
        led0.flush()
        led1.clear()
        led1.write(shutdown_display.value_text)
        led1.flush()
        logger.info(
            "Shutdown display applied: alpha=%r value=%r, panel off",
            shutdown_display.alpha_text, shutdown_display.value_text,
        )

    def onSigterm(signum, frame) -> None:
        # `systemctl stop` sends SIGTERM, not SIGINT -- Python's default
        # SIGTERM handling is to terminate immediately with no cleanup, so
        # without this handler the shutdown display/panel state below
        # would never run under systemd (only Ctrl+C's SIGINT reaches the
        # KeyboardInterrupt path).
        performShutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, onSigterm)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        performShutdown()


if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument(
        '-c', '--config',
        dest='config_path',
        default=None,
        help="Path to the config INI file (default: src/config.ini)",
    )
    args = arg_parser.parse_args()
    config = Config(args.config_path)

    formatter = logging.Formatter(
        fmt='%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s',
        datefmt='%M:%S'
    )
    logger = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(config.logging().level)

    main(config)
