from typing import List, Optional, Tuple
class TextDiff:
    def __init__(self, **kwargs) -> None:
        #self._width = kwargs.get('text', 'msx_text_width')
        self._buffer: list[tuple[str, bool]] = [('', False)]

    def getDiff(self, newText : str
        , dp_flags: Optional[List[bool]] = None
        , ignoreChars = [' ']
        ) -> List[Tuple[int, str, bool]]:
        if dp_flags is None:
            dp_flags = [False] * len(newText)
        output = []
        i = 0
        for c, dp in zip(newText, dp_flags):
            if i >= len(self._buffer):
                self._buffer.append(('', False)) # expand buffer
            cell = (c, dp)
            if self._buffer[i] != cell:
                self._buffer[i] = cell
                if c not in ignoreChars:
                    output.append((i, c, dp))
            i += 1
            #print(self._buffer)
        return output


if __name__ == "__main__":
    diff = TextDiff()
    output = diff.getDiff('     ')
    print(output)
    output = diff.getDiff('   l ')
    print(output)
    output = diff.getDiff('H  l ')
    print(output)
    output = diff.getDiff('Hello')
    print(output)