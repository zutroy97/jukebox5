import configparser
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class AnimationConfig:
    delay_between_characters_s: Optional[float] = None
    delay_after_line_finished_s: Optional[float] = None
    delay_after_animation_finished_s: Optional[float] = None


@dataclass(frozen=True)
class PanelConfig:
    name: str
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MQTTConfig:
    broker_host: str = "localhost"
    broker_port: int = 1883
    base_topic: str = "shairport-sync"


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
        return AnimationConfig(
            delay_between_characters_s=section.getfloat("delay_between_characters_s", fallback=None),
            delay_after_line_finished_s=section.getfloat("delay_after_line_finished_s", fallback=None),
            delay_after_animation_finished_s=section.getfloat("delay_after_animation_finished_s", fallback=None),
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

    def playlist_path(self) -> Optional[str]:
        if "playlist" not in self._parser:
            return None
        return self._parser["playlist"].get("path") or None
