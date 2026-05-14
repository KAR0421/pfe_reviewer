"""Check modules — importing this package registers every check.

The runner does ``from .. import checks`` to trigger these imports so
each ``@register_check`` decorator runs and populates ``CHECKS``.
"""

from . import performance  # noqa: F401  (registers SR030, SR031)
from . import logic  # noqa: F401  (registers SR020, SR021)
from . import logs  # noqa: F401  (registers SR090, SR091)
from . import docs  # noqa: F401  (registers SR010, SR012.1)
from . import lang_semantics  # noqa: F401  (registers SR059)
from . import metadata  # noqa: F401  (registers SR011, SR060, SR061, SR062)
