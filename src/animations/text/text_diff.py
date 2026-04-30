from typing import List, Tuple
class TextDiff:
    def __init__(self, **kwargs) -> None:
        #self._width = kwargs.get('text', 'msx_text_width')
        self._buffer = ['']

    def getDiff(self, newText : str) -> List[Tuple[int, str]]:
        output = []
        i = 0
        for c in newText:
            if i >= len(self._buffer):
                self._buffer.append('') # expand buffer
            if self._buffer[i] != c:
                output.append((i,c))
                self._buffer[i] = c
            i += 1
            #print(self._buffer)
        return output


if __name__ == "__main__":
    diff = TextDiff()
    output = diff.getDiff('   l ')
    print(output)
    output = diff.getDiff('H  l ')
    print(output)
    output = diff.getDiff('Hello')
    print(output)