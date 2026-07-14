from enum import Enum


class ObserverStates(Enum):
    """Shared by both the `observers` and `animations` packages (clear
    animators need to read/set an observer's `_state`). Deliberately kept as
    a standalone top-level module with zero dependencies: putting it inside
    the `observers` package created a circular import — any module in
    `animations` that needed it would trigger `observers/__init__.py`,
    which imports observer modules that import back into `animations`."""

    IDLE = 0
    ANIMATING = 1
    TEXT_UPDATED = 2
    ANIMATION_FINISHED = 3
    ANIMATION_LINE_FINISHED = 4
    START_ANIMATION = 5
    ANIMATION_DELAY = 6
    DISPLAY_CLEARING_START = 7
    DISPLAY_CLEARING = 8
    DISPLAY_CLEARED = 9
    DELAY_START = 10
    DELAYING = 11
    ANIMATION_FINISHED_DELAY = 12
    ANIMATION_FINISHED_DELAY_COMPLETE = 13
    ANIMATION_LINE_FINISHED_DELAY = 14
    ANIMATION_LINE_FINISHED_DELAY_COMPLETE = 15
    INITIALIZED = 16
    CHARACTER_REVEALING = 17
