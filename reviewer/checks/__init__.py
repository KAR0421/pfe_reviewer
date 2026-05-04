"""Check modules — importing this package registers every check.

The runner does ``from .. import checks`` to trigger these imports so
each ``@register_check`` decorator runs and populates ``CHECKS``.
"""

from . import performance  # noqa: F401  (registers SR030)
