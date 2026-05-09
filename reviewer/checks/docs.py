"""Documentation checks (SR010..SR012).

Currently implements:
- SR010 missing or empty ``USER_COMMENT``.
- SR012.1 insufficient inline-comment density relative to script
  complexity.

SR012.2 (the "comments describe how instead of why" rule) is the
agentic-phase check and lives outside this module.
"""
from __future__ import annotations

from ..ast.nodes import Script
from ..engine.registry import register_check
from ..engine.visitor import Check
from .logs import _count_complexity


@register_check(
    rule_id="SR010",
    category="docs",
    severity="error",
    description="Missing or empty USER_COMMENT.",
)
class MissingUserCommentCheck(Check):
    """Flag BizRules whose ``USER_COMMENT`` field is empty.

    Implements SPEC §8 SR010. The legacy version
    (``check_minimal_documentation``) returns one issue string when
    ``bizrule.comment`` is falsy or whitespace; the AST version emits
    a structured ``Finding`` with severity / category / rule-id so the
    Bitbucket reporter can grade it later.
    """

    def visit_Script(self, node: Script) -> None:
        comment = getattr(self.ctx.bizrule, "comment", None) or ""
        if comment.strip():
            return
        self.ctx.emit(
            line=1,
            message="Missing or empty USER_COMMENT",
        )


# ── SR012.1 InlineCommentDensityCheck ──────────────────────────────


# One ``// ...`` comment per ``_COMMENT_DENSITY_RATIO`` units of
# complexity (branches + loops + risky calls). Conservative on
# purpose: assignments don't need explanations, but a script with
# many decisions and zero inline notes is unmaintainable. Matches
# the ratio documented in SPEC §8 SR012.1 footnote.
_COMMENT_DENSITY_RATIO: int = 12


@register_check(
    rule_id="SR012.1",
    category="docs",
    severity="warning",
    description=(
        "Insufficient inline-comment density relative to script "
        "branching / loop / risky-call complexity."
    ),
)
class InlineCommentDensityCheck(Check):
    """Flag scripts with many non-obvious constructs but few inline
    ``// ...`` comments.

    Implements SPEC §8 SR012.1. There is no legacy counterpart — this
    rule only became feasible once the tokenizer started preserving
    comments on a side channel (``CheckContext.comments``) and the
    SR091 check landed ``_count_complexity``.

    Complexity matches SR091's definition (branches + loops + risky
    calls). The check is silent on trivial scripts (zero complexity)
    so a 10-line assignment block with no comments doesn't fire.
    """

    def visit_Script(self, node: Script) -> None:
        complexity = _count_complexity(node)
        if complexity == 0:
            return
        comments = len(self.ctx.comments)
        if comments * _COMMENT_DENSITY_RATIO >= complexity:
            return
        self.ctx.emit(
            line=1,
            message=(
                f"Insufficient inline comments: {comments} "
                f"`//` comment(s) for {complexity} branches/loops/"
                f"risky calls (need at least 1 comment per "
                f"{_COMMENT_DENSITY_RATIO} complex constructs)"
            ),
        )
