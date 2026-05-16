
import asyncio

from animations.text import AnimationChain, AnimationChainLink, MultiLineGenerator, Slide, TextDiff 

from .observer_base import UpdateEventType, ObserverBase
from drivers import abstract_line_display

class SingleLineAnimatedObserver(ObserverBase):
    async def on_multiline_finished(anim: abstract_line_display) -> bool:
        #print("MultiLineGenerator finished!")
        await asyncio.sleep(1.0)
        return True 

    async def on_slide_finished( anim: abstract_line_display) -> bool:
        #print("Slide finished!")
        await asyncio.sleep(2.0)
        return True

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._driver : abstract_line_display = kwargs.get('driver', None)
        self._event_type : UpdateEventType = kwargs.get('event_type', None)
        self._text : str = ""
        self._anim = None
        self._diff = TextDiff()
        self._textUpdateNeeded : bool = False

    def UpdateReceived(self, update_type: UpdateEventType, **kwargs) -> None:
        '''Called when an update is received'''
        if self._event_type is None or update_type != self._event_type:
            return
    
        value = kwargs.get('value', self._text)
        if value != self._text:
            self._text = value
            self._textUpdateNeeded = True

    async def loop(self) -> None:
        while self._is_running:
            if self._textUpdateNeeded:
                print(f"Text update needed, creating new animation for text: {self._text}")
                self._anim = AnimationChain(
                    max_text_width=self._driver.Width,
                    links=[
                        AnimationChainLink(MultiLineGenerator, onFinished=SingleLineAnimatedObserver.on_multiline_finished),
                        AnimationChainLink(Slide, onFinished=SingleLineAnimatedObserver.on_slide_finished),
                    ], text=self._text) 
                self._diff = TextDiff()
                await self._driver.clear()
                await self._anim.Start()
                self._textUpdateNeeded = False
            if self._anim is not None:
                next = await self._anim.Next()
                if next:
                    text = await self._anim.GetText()
                    chars = self._diff.getDiff(text)
                    for pos, c in chars:
                        await self._driver.write_at_position(pos, c)
            await asyncio.sleep(0.1)  # Simulate some work