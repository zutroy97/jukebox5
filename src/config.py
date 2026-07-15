import configparser
import os
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


class Config:
    """Parses the jukebox's INI config file (defaults to src/config.ini).

    Section naming conventions used by the file:
      - `display<width>Animation<n>`: per-display animation timing, keyed by
        the display's character width (e.g. [display8Animation1] applies to
        an 8-character-wide display).
      - `jukeboxPanel`: has a single `option` key naming which of the
        `jukeboxPanel<n>` sections is active.
      - `mqtt`: shairport-sync MQTT broker connection settings.
      - `playlist`: optional override path for the playlist JSON file.
      - `display`: has a `fields` key listing which song fields (artist,
        title, album) to cycle through on the animated displays, and in
        what order.
      - `trackSelectionFeedback`: blink/error timing shown on the 4-digit
        display after a keypad track selection completes.
      - `playbackPauseFlash`: flash timing for the 4-digit display while
        playback is paused.
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

    def playlist_path(self) -> Optional[str]:
        if "playlist" not in self._parser:
            return None
        return self._parser["playlist"].get("path") or None

    def display_fields(self) -> list:
        if "display" not in self._parser:
            return list(DISPLAY_FIELDS)

        raw = self._parser["display"].get("fields", fallback="")
        fields = [f.strip().lower() for f in raw.split(",") if f.strip()]
        unknown = [f for f in fields if f not in DISPLAY_FIELDS]
        if unknown:
            raise ValueError(f"[display] fields has unknown value(s) {unknown}; valid values are {DISPLAY_FIELDS}")

        return fields or list(DISPLAY_FIELDS)
