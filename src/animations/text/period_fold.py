def fold_periods(text: str) -> tuple[str, list[bool]]:
    """Fold '.'/',' into the decimal-point flag of the preceding character
    instead of letting them consume their own display cell, matching the
    HT16K33/Seg14x4 hardware's own DP-segment behavior (see
    AbstractLED16Animator.string_to_char_mask, which does the same thing
    but converts straight to segment patterns -- this keeps plain
    characters instead, since callers need the glyph itself).

    Returns (folded_text, dp_flags) -- same length; dp_flags[i] is True if
    folded_text[i]'s cell should also light its decimal-point segment. A
    leading '.'/',' with nothing before it can't fold onto anything, so
    it's kept as its own (flagless) cell.
    """
    chars: list[str] = []
    dp_flags: list[bool] = []
    for c in text:
        if c in ('.', ',') and chars:
            dp_flags[-1] = True
        else:
            chars.append(c)
            dp_flags.append(False)
    return ''.join(chars), dp_flags
