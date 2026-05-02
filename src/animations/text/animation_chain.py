from typing import Type, TypeVar, Awaitable
from collections.abc import Callable
from .base import TextAnimatorBase

import asyncio

class AnimationChainLink():
    def __init__(self, anim_type: Type[TextAnimatorBase], onFinished: Callable[[TextAnimatorBase], Awaitable[bool]] | None = None) -> None:
        if onFinished is not None and not callable(onFinished):
            raise TypeError("onFinished must be callable or None")
        self._anim_type = anim_type
        self._onFinished = onFinished

class AnimationChain(TextAnimatorBase):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._links : list[AnimationChainLink] = kwargs.get('links', [])
        self._args = kwargs
        self._animators : list[TextAnimatorBase] = []

    async def Start(self) -> None:
        self._animators = []
        anim = self._links[0]._anim_type(text=self.text, max_text_width=self.max_text_width)
        await anim.Start()
        self._animators.append(anim)
        await self._initialiazeAnimations(1)

    async def Next(self) -> bool:
        '''Returns true if more data is available'''
        return await self._nextCheck(len(self._animators)-1)

    async def _nextCheck(self, index: int) -> bool:
        if index < 0:
            #self._logger.debug(f"Index {index} is out of range, returning False")
            return False
        anim = self._animators[index]
        if await anim.Next():
            #self._logger.debug(f"Animation at index {index} has more data available")
            return True
        link = self._links[index]
        if link._onFinished:
            #self._logger.debug(f"Checking onFinished callback for animation at index {index}")
            result = await link._onFinished(anim)
            if False == result:
                return False
        parentNextResult = await self._nextCheck(index-1)
        #self._logger.debug(f"Parent next result for animation at index {index}: {parentNextResult}")
        if True == parentNextResult:
            parentText = await self._animators[index-1].GetText()
            anim = self._links[index]._anim_type(text=parentText, max_text_width=self.max_text_width)
            await anim.Start()
            self._animators[index]=anim
            return True
        
        #self._logger.debug(f"Animation at index {index} has no more data available")
        return False


    async def GetText(self) -> str:
        return await self._animators[-1].GetText()

    async def _initialiazeAnimations(self, index: int) -> None:
        if index < len(self._links):
            anim = self._links[index]._anim_type(text= await self._animators[index-1].GetText()
                , max_text_width=self.max_text_width)
            await anim.Start()
            self._animators.append(anim)
            await self._initialiazeAnimations(index+1)
        return
