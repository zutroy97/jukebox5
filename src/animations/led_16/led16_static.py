from .abstract_led16_animator import AbstractLED16Animator
from ..text.abstract_text_animator import AbstractTextAnimator

class LED16Static(AbstractLED16Animator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._read : bool = False

    def Start(self) -> None:
        self._read = False

    def Next(self) -> bool:
        if not self._read:
            self._read = True
            return True
        return False

    def GetSegments(self) -> list[int]:
        return self.string_to_char_mask(self.text[:self.max_text_width])
    

    
