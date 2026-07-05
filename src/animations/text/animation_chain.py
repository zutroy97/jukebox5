from typing import Type
from collections.abc import Callable
from .abstract_text_animator import AbstractTextAnimator


class AnimationChainLink:
    def __init__(self, anim_type: Type[AbstractTextAnimator], onFinished: Callable[[AbstractTextAnimator], bool] | None = None) -> None:
        if onFinished is not None and not callable(onFinished):
            raise TypeError("onFinished must be callable or None")
        self._anim_type = anim_type
        self._onFinished = onFinished


class AnimationChain(AbstractTextAnimator):
    """Runs a sequence of animators back-to-back: once link N's Next()
    reports it's out of frames, link N+1 is started (seeded with link N's
    final text) and takes over."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._links: list[AnimationChainLink] = kwargs.get('links', [])
        self._animators: list[AbstractTextAnimator] = []

    def Start(self) -> None:
        first = self._links[0]._anim_type(text=self.text, max_text_width=self.max_text_width)
        first.Start()
        self._animators = [first]
        for index in range(1, len(self._links)):
            anim = self._links[index]._anim_type(
                text=self._animators[index - 1].GetText(),
                max_text_width=self.max_text_width,
            )
            anim.Start()
            self._animators.append(anim)

    def Next(self) -> bool:
        '''Returns true if more data is available'''
        return self._next_from(len(self._animators) - 1)

    def _next_from(self, index: int) -> bool:
        if index < 0:
            return False

        anim = self._animators[index]
        if anim.Next():
            return True

        link = self._links[index]
        if link._onFinished and link._onFinished(anim) is False:
            return False

        if not self._next_from(index - 1):
            return False

        parent_text = self._animators[index - 1].GetText()
        anim = self._links[index]._anim_type(text=parent_text, max_text_width=self.max_text_width)
        anim.Start()
        self._animators[index] = anim
        return True

    def GetText(self) -> str:
        return self._animators[-1].GetText()
