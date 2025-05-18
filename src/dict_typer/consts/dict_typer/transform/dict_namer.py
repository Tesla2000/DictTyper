from __future__ import annotations

from typing import Final

HARD_CODED_KEYS_TRUE: Final[
    str
] = """Can return value of this function be replaced with a TypedDict. True if the keys are hardcoded, False otherwise.
Example: True if
def foo():
    return {'foo': 'bar'}
Example: True if
def foo():
    return dict(foo=bar)
Example: False if
def foo(kwargs):
    return dict(kwargs)
Example: False if
def foo(kwargs):
    return {}
"""
RETURN_DICT_EMPTY: Final[
    str
] = """You job is to replace return value of the function with a TypedDict if it is possible.
Peak the value in the way that you are 100% sure that the return value matches the typed dict that you propose.
Peak suitable field names for the typed dict's fields which represent keys of the dict, types hints which represent type of values and the name of the typeddict that is a return value of the function bellow.
Return only key names that are present as strings or kwargs in the code.
If type hints are provided by return definition you can use them for greater precision
Note field names must be single word or words connected with _:
"""
