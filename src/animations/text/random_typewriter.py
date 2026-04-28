import random
import asyncio
from base import TextAnimatorBase

class RandomTypeWriter(TextAnimatorBase):
    def __init__(self,  **kwargs) -> None:
        super().__init__(**kwargs)
        self._character_queue = []
        self._frameBuffer : list[str] = []
        
    async def Start(self) -> None:
        self._text = self.text[:self.max_text_width] # truncate text to max width if necessary
        self._character_queue = list(range(0, len(self.text)))
        random.shuffle(self._character_queue)
        self._frameBuffer = list(' ' * len(self.text)) # empty string of the same length as text, to be filled in as the animation progresses   

    async def Next(self) -> bool:
        '''Returns true if more data is available'''
        return len(self._character_queue) > 0

    async def GetText(self) -> str:
        '''Returns the text to be displayed'''
        x = self._character_queue.pop(0)
        self._frameBuffer[x] = self.text[x]
        return ''.join(self._frameBuffer).ljust(self.max_text_width)

async def main():    
    anim = RandomTypeWriter(text="Should display the text one character at a time, in a random order."
        , max_text_width=80)
   
    await anim.Start()
    while await anim.Next():
        text = await anim.GetText()
        print(f'\r{text}', end='')
        #print(f"Frame {cnt:>3}: {await anim.GetText()}")
        await asyncio.sleep(0.1)
        #print(f"Text Length: {len(anim.text)} Frames: {cnt}")
    print()



if __name__ == "__main__":
    asyncio.run(main())    