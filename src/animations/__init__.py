from .text.multiline_generator import MultiLineGenerator
from .text.random_typewriter import RandomTypeWriter
from .text.slide import Slide

from .text.static import Static

from .text.text_diff import TextDiff
from .text.animation_chain import AnimationChainLink, AnimationChain
from .text.abstract_text_animator import AbstractTextAnimator
from .text.period_fold import fold_periods

from .led_16.alien import AlienAnimator as AlienLED16Animator
from .led_16.led16_static import LED16Static
from .led_16.abstract_led16_animator import AbstractLED16Animator
from .led_16.text_animator_adapter import LED16TextAnimatorAdapter


__all__ = ['AlienLED16Animator', 'LED16Static', 'LED16TextAnimatorAdapter',
            'AbstractTextAnimator', 'MultiLineGenerator', 'RandomTypeWriter', 'Slide',
             'TextDiff', 'AnimationChainLink', 'AnimationChain', 'AbstractLED16Animator'
             , 'Static', 'fold_periods'
            ]