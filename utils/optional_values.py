"""Shared value semantics for optional inputs.

A missing value is represented as Python ``None`` on the data output, paired
with a BOOLEAN presence output.  Presence is decided strictly by identity
(``value is not None``); the contents of a value are never inspected.  An
all-black image is a *present* image.

The string ``NONE_SELECTION`` ("none") is the combo value used by
``Optional Load Image`` to explicitly select "no image".
"""

NONE_SELECTION = "none"


def has_value(value) -> bool:
    """Return True if *value* represents a present, usable value.

    Only ``None`` counts as absent.  Anything else — including zero-filled
    tensors, empty strings and empty batches — is considered present, because
    "empty" is a property of the data, not of its existence.
    """
    return value is not None
