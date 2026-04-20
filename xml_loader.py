import xml.etree.ElementTree as ET
import re

def load_company_xml(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove XML declaration
    content = re.sub(r"<\?xml.*?\?>", "", content)

    # Escape stray &
    content = re.sub(r"&(?!(?:amp|lt|gt|quot|apos);)", "&amp;", content)

    # Temporarily replace <IMPACT> content with placeholder
    impact_map = {}
    def replace_impact(match):
        key = f"__IMPACT_{len(impact_map)}__"
        impact_map[key] = match.group(1)
        return f"<IMPACT>{key}</IMPACT>"

    content = re.sub(r"<IMPACT.*?>(.*?)</IMPACT>", replace_impact, content, flags=re.DOTALL)

    # Wrap in a root element
    wrapped = f"<ROOT>{content}</ROOT>"

    root = ET.fromstring(wrapped)

    # Restore IMPACT content after parsing
    for impact_elem in root.findall(".//IMPACT"):
        key = impact_elem.text
        if key in impact_map:
            impact_elem.text = impact_map[key]

    return root