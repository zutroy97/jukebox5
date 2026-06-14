import random

from .abstract_led16_animator import AbstractLED16Animator

class AlienAnimator(AbstractLED16Animator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._segment_list :list[list[int]] = []

    async def Start(self) -> None:
        self._segment_list.clear()
        raw_segments : list[int] = self.string_to_char_mask(self.text)

        #for segId in self._make_shuffled_list():
        for segId in list(range(14)):
            l = []
            #self._logger.debug(f"Adding segment {segId} to animation")
            columnCnt = 0
            for seg in raw_segments:
                if len(self._segment_list) == 0:
                    l.append(seg & (1 << segId))
                else:
                    l.append(seg & (1 << segId) |self._segment_list[-1][columnCnt])
                columnCnt += 1
            #self._logger.debug(f"Segment list: {rowCnt}:{l}")
            if all(val == 0 for val in l):
                continue
            self._segment_list.append(l)
            
     

    async def Next(self) -> bool:
        return len(self._segment_list) > 0

    async def GetSegments(self) -> list[int]:
        return self._segment_list.pop(0) if self._segment_list else [0] * len(self.text)
    
    def _make_shuffled_list(self) -> list[int]:
        numbers = list(range(14))
        random.shuffle(numbers)
        return numbers