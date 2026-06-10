from .abstract_led16_animator import AbstractLED16Animator
from ..text.abstract_text_animator import AbstractTextAnimator

class LED16TextAnimatorAdapter(AbstractLED16Animator):
    '''An adapter that allows using a text animator as a LED16 animator.'''
    def __init__(self, text_animator: AbstractTextAnimator, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text_animator = text_animator

    async def Start(self) -> None:
        await self._text_animator.Start()

    async def Next(self) -> bool:
        return await self._text_animator.Next()

    async def GetSegments(self) -> list[int]:
        text = await self._text_animator.GetText()
        return self.string_to_char_mask(text)