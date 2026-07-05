from .abstract_led16_animator import AbstractLED16Animator
from ..text.abstract_text_animator import AbstractTextAnimator

class LED16TextAnimatorAdapter(AbstractLED16Animator):
    '''An adapter that allows using a text animator as a LED16 animator.'''
    def __init__(self, text_animator: AbstractTextAnimator, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text_animator = text_animator

    def Start(self) -> None:
        self._text_animator.Start()

    def Next(self) -> bool:
        return self._text_animator.Next()

    def GetSegments(self) -> list[int]:
        text = self._text_animator.GetText()
        return self.string_to_char_mask(text)