from .abstract_led16_animator import AbstractLED16Animator


class AlienAnimator(AbstractLED16Animator):
    """Reveals each character's 14 segments one bit-position at a time,
    building up every character in the string simultaneously across frames
    (rather than one full character at a time) for a glitchy reveal effect."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._segment_list: list[list[int]] = []

    def Start(self) -> None:
        self._segment_list.clear()
        raw_segments: list[int] = self.string_to_char_mask(self.text)

        for bit in range(14):
            frame = []
            for column, seg in enumerate(raw_segments):
                revealed_bit = seg & (1 << bit)
                previous = self._segment_list[-1][column] if self._segment_list else 0
                frame.append(revealed_bit | previous)
            if any(frame):
                self._segment_list.append(frame)

    def Next(self) -> bool:
        return len(self._segment_list) > 0

    def GetSegments(self) -> list[int]:
        return self._segment_list.pop(0) if self._segment_list else [0] * len(self.text)