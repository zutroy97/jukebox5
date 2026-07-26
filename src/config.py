import configparser
import os
import socket
from dataclasses import dataclass, field
from typing import Optional

DISPLAY_FIELDS = ("artist", "title", "album")


CHARACTER_REVEAL_ANIMATIONS = ("immediate", "segment")


@dataclass(frozen=True)
class AnimationConfig:
    delay_between_characters_s: Optional[float] = None
    delay_after_line_finished_s: Optional[float] = None
    delay_after_animation_finished_s: Optional[float] = None
    delay_between_segments_s: Optional[float] = None
    # "immediate" (CharacterRevealImmediatelyAnimator, whole character at
    # once) or "segment" (SegmentByCharacterRevealAnimator, one segment at
    # a time). None means: caller's own default.
    character_reveal_animation: Optional[str] = None


@dataclass(frozen=True)
class PanelConfig:
    name: str
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MQTTConfig:
    broker_host: str = "localhost"
    broker_port: int = 1883
    base_topic: str = "shairport-sync"
    # Seconds to wait for the broker to PUBACK a remote-control command
    # (see ShairportSyncMQTTSource.send_remote_command) before treating that
    # path as unresponsive and falling back to sshWorker's AirPlay recovery.
    remote_command_timeout_s: float = 5.0


@dataclass(frozen=True)
class TrackSelectionFeedbackConfig:
    """Feedback shown on the 4-digit display after a 3-digit keypad
    selection completes, before it reverts to the current-track display."""
    blink_count: int = 3
    blink_phase_s: float = 0.25
    error_text: str = "Err"
    error_duration_s: float = 2.0


@dataclass(frozen=True)
class PlaybackPauseFlashConfig:
    """Flash timing for the 4-digit display while playback is paused."""
    flash_interval_s: float = 0.75


@dataclass(frozen=True)
class SSHWorkerConfig:
    """Connection settings for MusicAppSSHWorker -- the SSH link to the
    machine running the macOS Music app, used for commands that
    shairport-sync's own MQTT metadata has no equivalent for."""
    host: str
    username: str
    key_path: str
    port: int = 22
    keepalive_interval_s: float = 30.0
    reconnect_delay_s: float = 5.0
    connect_timeout_s: float = 10.0
    strict_host_key_checking: bool = False
    # Name of the AirPlay device the recovery script should select. Defaults
    # to this machine's own hostname, since that's what shairport-sync
    # advertises itself as over AirPlay unless configured otherwise --
    # unrelated to playlist_name below.
    airplay_device_name: str = field(default_factory=socket.gethostname)
    # Music.app playlist the recovery script should start playing if
    # nothing is already playing. An independent setting from
    # airplay_device_name -- don't assume the two match.
    playlist_name: str = "Jukebox"
    # How many times to attempt the recovery script before giving up, and
    # how long to wait between attempts.
    recovery_attempts: int = 3
    recovery_retry_delay_s: float = 5.0


class Config:
    """Parses the jukebox's INI config file (defaults to src/config.ini).

    Section naming conventions used by the file:
      - `display<width>Animation<n>`: per-display animation timing, keyed by
        the display's character width (e.g. [display8Animation1] applies to
        an 8-character-wide display).
      - `jukeboxPanel`: has a single `option` key naming which of the
        `jukeboxPanel<n>` sections is active.
      - `mqtt`: shairport-sync MQTT broker connection settings.
      - `display`: has a `fields` key listing which song fields (artist,
        title, album) to cycle through on the animated displays, and in
        what order.
      - `trackSelectionFeedback`: blink/error timing shown on the 4-digit
        display after a keypad track selection completes.
      - `playbackPauseFlash`: flash timing for the 4-digit display while
        playback is paused.
      - `sshWorker`: connection settings for the SSH link to the machine
        running the macOS Music app, plus the AirPlay device name and
        playlist name its recovery script
        (src/osx/scripts/recover_airplay_playback.js) should target --
        independent settings, not assumed to match each other. Section is
        optional; omitting it disables the feature entirely.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "config.ini")

        self._parser = configparser.ConfigParser()
        with open(path, "r") as f:
            self._parser.read_file(f)

    def animation_for_width(self, display_width: int) -> AnimationConfig:
        section_name = f"display{display_width}Animation1"
        if section_name not in self._parser:
            return AnimationConfig()

        section = self._parser[section_name]
        character_reveal_animation = section.get("character_reveal_animation", fallback=None)
        if character_reveal_animation is not None:
            character_reveal_animation = character_reveal_animation.strip().lower()
            if character_reveal_animation not in CHARACTER_REVEAL_ANIMATIONS:
                raise ValueError(
                    f"[{section_name}] character_reveal_animation {character_reveal_animation!r} "
                    f"is invalid; valid values are {CHARACTER_REVEAL_ANIMATIONS}"
                )

        return AnimationConfig(
            delay_between_characters_s=section.getfloat("delay_between_characters_s", fallback=None),
            delay_after_line_finished_s=section.getfloat("delay_after_line_finished_s", fallback=None),
            delay_after_animation_finished_s=section.getfloat("delay_after_animation_finished_s", fallback=None),
            delay_between_segments_s=section.getfloat("delay_between_segments_s", fallback=None),
            character_reveal_animation=character_reveal_animation,
        )

    def panel(self) -> PanelConfig:
        if "jukeboxPanel" not in self._parser or "option" not in self._parser["jukeboxPanel"]:
            raise ValueError("config.ini is missing a [jukeboxPanel] section with an 'option' key")

        section_name = self._parser["jukeboxPanel"]["option"]
        if section_name not in self._parser:
            raise ValueError(f"[jukeboxPanel] option '{section_name}' has no matching [{section_name}] section")

        section = self._parser[section_name]
        return PanelConfig(name=section.get("name", section_name), options=dict(section))

    def mqtt(self) -> MQTTConfig:
        if "mqtt" not in self._parser:
            return MQTTConfig()

        section = self._parser["mqtt"]
        return MQTTConfig(
            broker_host=section.get("broker_host", fallback="localhost"),
            broker_port=section.getint("broker_port", fallback=1883),
            base_topic=section.get("base_topic", fallback="shairport-sync"),
            remote_command_timeout_s=section.getfloat("remote_command_timeout_s", fallback=5.0),
        )

    def track_selection_feedback(self) -> TrackSelectionFeedbackConfig:
        if "trackSelectionFeedback" not in self._parser:
            return TrackSelectionFeedbackConfig()

        section = self._parser["trackSelectionFeedback"]
        return TrackSelectionFeedbackConfig(
            blink_count=section.getint("blink_count", fallback=3),
            blink_phase_s=section.getfloat("blink_phase_s", fallback=0.25),
            error_text=section.get("error_text", fallback="Err"),
            error_duration_s=section.getfloat("error_duration_s", fallback=2.0),
        )

    def playback_pause_flash(self) -> PlaybackPauseFlashConfig:
        if "playbackPauseFlash" not in self._parser:
            return PlaybackPauseFlashConfig()

        section = self._parser["playbackPauseFlash"]
        return PlaybackPauseFlashConfig(
            flash_interval_s=section.getfloat("flash_interval_s", fallback=0.75),
        )

    def ssh_worker(self) -> Optional[SSHWorkerConfig]:
        if "sshWorker" not in self._parser:
            return None

        section = self._parser["sshWorker"]
        missing = [key for key in ("host", "username", "key_path") if not section.get(key)]
        if missing:
            raise ValueError(f"[sshWorker] is missing required key(s): {missing}")

        return SSHWorkerConfig(
            host=section["host"],
            username=section["username"],
            key_path=section["key_path"],
            port=section.getint("port", fallback=22),
            keepalive_interval_s=section.getfloat("keepalive_interval_s", fallback=30.0),
            reconnect_delay_s=section.getfloat("reconnect_delay_s", fallback=5.0),
            connect_timeout_s=section.getfloat("connect_timeout_s", fallback=10.0),
            strict_host_key_checking=section.getboolean("strict_host_key_checking", fallback=False),
            airplay_device_name=section.get("airplay_device_name", fallback=None) or socket.gethostname(),
            playlist_name=section.get("playlist_name", fallback="Jukebox"),
            recovery_attempts=section.getint("recovery_attempts", fallback=3),
            recovery_retry_delay_s=section.getfloat("recovery_retry_delay_s", fallback=5.0),
        )

    def display_fields(self) -> list:
        if "display" not in self._parser:
            return list(DISPLAY_FIELDS)

        raw = self._parser["display"].get("fields", fallback="")
        fields = [f.strip().lower() for f in raw.split(",") if f.strip()]
        unknown = [f for f in fields if f not in DISPLAY_FIELDS]
        if unknown:
            raise ValueError(f"[display] fields has unknown value(s) {unknown}; valid values are {DISPLAY_FIELDS}")

        return fields or list(DISPLAY_FIELDS)
