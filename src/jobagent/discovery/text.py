"""HTML to plain text for posting descriptions.

Workday returns `jobDescription` as HTML, and extraction (#30) reads text. A
dependency for this would be hard to justify: the input is one field from one
known producer, and the rules that matter are narrow.

Structure is preserved where it carries meaning. A posting's requirements are a
list, and "5+ years of Python" on its own line is a different parsing problem
from the same words run into the middle of a paragraph. So block elements become
line breaks and list items keep a marker; everything else collapses.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# Elements that end a line. Workday nests dozens of bare <div>s around a single
# paragraph, so these must collapse rather than produce a page of blank lines.
_BLOCK = frozenset(
    {
        "p",
        "div",
        "br",
        "tr",
        "section",
        "article",
        "header",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "table",
        "blockquote",
    }
)
_SKIP = frozenset({"script", "style", "head"})

_BLANK_RUN = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]{2,}")


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skipping += 1
            return
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skipping = max(0, self._skipping - 1)
            return
        if tag in _BLOCK or tag == "li":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str | None) -> str:
    """Flatten a posting's HTML into readable text.

    Non-strict on purpose. A posting is third-party HTML written by whatever
    pasted into the requisition form, and refusing to parse it would mean losing
    the description over a stray tag.
    """
    if not html:
        return ""
    parser = _Extractor()
    parser.feed(html)
    parser.close()

    joined = "".join(parser.parts)
    # Non-breaking spaces survive entity decoding and break every later regex.
    joined = joined.replace("\xa0", " ")
    lines = [_SPACES.sub(" ", line).strip() for line in joined.splitlines()]
    lines = _rejoin_orphan_markers([line for line in lines if line])
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def _rejoin_orphan_markers(lines: list[str]) -> list[str]:
    """Reattach a list marker to text that landed on the next line.

    A `<li>` whose content is wrapped in a nested element emits the "-" and the
    text separately. TD does this, and it costs the bullet: a stranded "-" is an
    empty bullet, and the requirement under it stops looking like a requirement
    at all.
    """
    out: list[str] = []
    pending = False
    for line in lines:
        if line == "-":
            pending = True
            continue
        out.append(f"- {line}" if pending else line)
        pending = False
    return out
