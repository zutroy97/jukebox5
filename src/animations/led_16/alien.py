from .abstract_led16_animator import AbstractLED16Animator

class AlienAnimator(AbstractLED16Animator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._state = 0

    async def Start(self) -> None:
        self._state = 0

    async def Next(self) -> bool:
        self._state += 1
        return self._state < 8

    async def GetSegments(self) -> list[int]:
        return self.string_to_char_mask(self.text)