"""Read the labels and the KOGL (공공누리) statement shown on an eMuseum object page."""

import html
import re

PAGE_URL = "https://www.emuseum.go.kr/detail?relicId={}"
LABELS = {"명칭": "page_title", "국적/시대": "page_nationality_period", "분류": "page_classification", "재질": "page_material"}


def page_lines(page):
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_object_page(page):
    """Take the first detail block as shown; fields missing on the page stay empty."""
    lines = page_lines(page)
    fields = {name: "" for name in [*LABELS.values(), "page_kogl_type", "page_rights_statement"]}
    for index, line in enumerate(lines[:-1]):
        key = LABELS.get(line)
        if key and not fields[key]:
            fields[key] = lines[index + 1]
        match = re.fullmatch(r"제\s*(\d)\s*유형\s*:.*", line)
        if match and not fields["page_kogl_type"] and lines[index + 1].startswith("저작권 보호분야"):
            fields["page_kogl_type"] = match.group(1)
            fields["page_rights_statement"] = f"{line} / {lines[index + 1]}"
    return fields


def fetch_object_page(relic_id, session):
    response = session.get(PAGE_URL.format(relic_id), timeout=30)
    response.raise_for_status()
    return parse_object_page(response.text)
