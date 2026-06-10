from ..single_line_animated_simple_base import SingleLineAnimatedObserverBase
from ...drivers.led16_driver import led16_driver

class SingleLineLed16AnimatedObserver(SingleLineAnimatedObserverBase):
    '''An observer that displays a single line of text with animation on a LED16 display.'''
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "driver" not in kwargs:
            raise TypeError("Missing required keyword argument: 'driver'")
        self._driver : led16_driver = kwargs['driver']
        self._m
