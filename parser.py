# parser.py
import re

class BizRule:
    def __init__(self, name, comment, scope, script):
        self.name = name
        self.comment = comment
        self.scope = scope
        self.script = script

def extract_bizrules(xml_path):
    with open(xml_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all complete <SMARTRULE>...</SMARTRULE> blocks
    smartrules = re.findall(
        r"<SMARTRULE\b.*?>.*?</SMARTRULE>",
        content,
        flags=re.DOTALL | re.IGNORECASE
    )

    rules = []

    for block in smartrules:
        # Extract FIND attribute as scope
        scope_match = re.search(r'FIND="([^"]*)"', block, flags=re.IGNORECASE)
        scope = scope_match.group(1) if scope_match else ""

        # Extract RULE_CODE
        code_match = re.search(
            r"<RULE_CODE.*?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</RULE_CODE>",
            block,
            flags=re.DOTALL | re.IGNORECASE
        )
        code = code_match.group(1).strip() if code_match else ""

        # Extract USER_COMMENT
        comment_match = re.search(
            r"<USER_COMMENT.*?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</USER_COMMENT>",
            block,
            flags=re.DOTALL | re.IGNORECASE
        )
        comment = comment_match.group(1).strip() if comment_match else ""

        # Extract IMPACT script
        impact_match = re.search(
            r"<IMPACT.*?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</IMPACT>",
            block,
            flags=re.DOTALL | re.IGNORECASE
        )
        impact = impact_match.group(1).strip() if impact_match else ""

        rules.append(BizRule(
            name=code,
            comment=comment,
            scope=scope,
            script=impact
        ))

    return rules