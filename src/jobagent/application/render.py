"""Render a tailored variant to PDF and DOCX.

Layout is chosen by what parses, not by what looks clever: single column,
standard headings, no tables, no text inside graphics, embedded standard fonts.
A visually sophisticated resume that an ATS reads as gibberish has failed at its
only job.

Both formats come from one structure, so they cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobagent.application.resume import Resume
from jobagent.application.tailor import TailoredResume


@dataclass(frozen=True)
class RenderedDocuments:
    pdf: Path
    docx: Path


def _contact_line(resume: Resume) -> str:
    c = resume.contact
    parts = [c.location, c.phone, c.email]
    if c.linkedin:
        parts.append(c.linkedin)
    if c.github:
        parts.append(c.github)
    return "  |  ".join(parts)


def _role_heading(title: str, org: str, location: str, start: str, end: str | None) -> str:
    return f"{title}  |  {org}  |  {location}  |  {start} - {end or 'Present'}"


def render_pdf(resume: Resume, tailored: TailoredResume, path: Path) -> Path:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        BaseDocTemplate,
        Flowable,
        Frame,
        ListFlowable,
        ListItem,
        PageTemplate,
        Paragraph,
        Spacer,
    )

    black = HexColor("#000000")
    rule_colour = HexColor("#333333")

    name_style = ParagraphStyle(
        "name",
        fontName="Helvetica-Bold",
        fontSize=19,
        leading=22,
        alignment=1,
        spaceAfter=2,
        textColor=black,
    )
    contact_style = ParagraphStyle(
        "contact",
        fontName="Helvetica",
        fontSize=8.7,
        leading=11,
        alignment=1,
        spaceAfter=4,
        textColor=black,
    )
    section_style = ParagraphStyle(
        "section",
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        spaceBefore=5.5,
        spaceAfter=1,
        textColor=black,
    )
    body_style = ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=9.0,
        leading=11.0,
        alignment=TA_JUSTIFY,
        textColor=black,
    )
    role_style = ParagraphStyle(
        "role",
        fontName="Helvetica",
        fontSize=9.3,
        leading=11.4,
        spaceBefore=3,
        textColor=black,
    )

    class HRule(Flowable):
        def __init__(self, width: float) -> None:
            super().__init__()
            self.width = width
            self.height = 2.1

        def draw(self) -> None:
            self.canv.setStrokeColor(rule_colour)
            self.canv.setLineWidth(0.6)
            self.canv.line(0, 1, self.width, 1)

    margin = 0.52 * inch
    doc = BaseDocTemplate(
        str(path),
        pagesize=LETTER,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=0.40 * inch,
        bottomMargin=0.36 * inch,
        title=f"{resume.contact.name} - Resume",
        author=resume.contact.name,
        subject=f"{tailored.posting.title} at {tailored.posting.company}",
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="main",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame])])

    story: list[Any] = [
        Paragraph(resume.contact.name, name_style),
        Paragraph(_contact_line(resume), contact_style),
    ]

    def section(title: str) -> None:
        story.append(Paragraph(title.upper(), section_style))
        story.append(HRule(doc.width))

    def bullets(items: list[str]) -> None:
        story.append(
            ListFlowable(
                [ListItem(Paragraph(t, body_style), leftIndent=11) for t in items],
                bulletType="bullet",
                start="•",
                leftIndent=11,
                bulletFontSize=7,
                bulletOffsetY=-0.5,
                spaceBefore=0,
                spaceAfter=0,
            )
        )

    section("Summary")
    story.append(Paragraph(resume.summary, body_style))

    section("Education")
    for edu in resume.education:
        story.append(
            Paragraph(
                f"<b>{edu.school}</b>, {edu.location}<br/>{edu.credential} "
                f"&nbsp;|&nbsp; {edu.graduation}",
                role_style,
            )
        )
        if edu.coursework:
            story.append(Spacer(1, 1.5))
            story.append(Paragraph("Relevant coursework: " + ", ".join(edu.coursework), body_style))

    section("Experience")
    for tailored_role in tailored.roles:
        r = tailored_role.role
        story.append(
            Paragraph(
                f"<b>{r.title}</b> &nbsp;|&nbsp; {r.organization} &nbsp;|&nbsp; "
                f"{r.location} &nbsp;|&nbsp; {r.start} - {r.end or 'Present'}",
                role_style,
            )
        )
        story.append(Spacer(1, 1))
        bullets([b.text for b in tailored_role.bullets])

    if resume.projects:
        section("Projects")
        for project in resume.projects:
            head = f"<b>{project.name}</b>"
            if project.tech:
                head += " &nbsp;|&nbsp; " + ", ".join(project.tech)
            if project.date:
                head += f" &nbsp;|&nbsp; {project.date}"
            story.append(Paragraph(head, role_style))
            story.append(Spacer(1, 1))
            bullets([a.text for a in project.accomplishments])

    if resume.skills:
        section("Technical Skills")
        for label, items in resume.skills.items():
            story.append(Paragraph(f"<b>{label}:</b> " + ", ".join(items), body_style))

    doc.build(story)
    return path


def render_docx(resume: Resume, tailored: TailoredResume, path: Path) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    for section_obj in doc.sections:
        section_obj.top_margin = Inches(0.40)
        section_obj.bottom_margin = Inches(0.36)
        section_obj.left_margin = Inches(0.52)
        section_obj.right_margin = Inches(0.52)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(9.5)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 1.0
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")

    def para(before: float = 0, after: float = 0, align: Any = None) -> Any:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.space_after = Pt(after)
        if align is not None:
            p.alignment = align
        return p

    def run(p: Any, text: str, bold: bool = False, size: float = 9.5) -> None:
        r = p.add_run(text)
        r.bold = bold
        r.font.size = Pt(size)
        r.font.color.rgb = RGBColor(0, 0, 0)

    def rule(p: Any) -> None:
        pPr = p._p.get_or_add_pPr()
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "333333")
        borders.append(bottom)
        pPr.append(borders)

    def heading(title: str) -> None:
        p = para(before=6, after=2)
        run(p, title.upper(), bold=True, size=10)
        rule(p)

    def bullet(text: str) -> None:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.left_indent = Inches(0.20)
        p.paragraph_format.first_line_indent = Inches(-0.13)
        run(p, text)

    p = para(after=1, align=WD_ALIGN_PARAGRAPH.CENTER)
    run(p, resume.contact.name, bold=True, size=19)
    p = para(after=4, align=WD_ALIGN_PARAGRAPH.CENTER)
    run(p, _contact_line(resume), size=8.7)

    heading("Summary")
    run(para(after=1), resume.summary)

    heading("Education")
    for edu in resume.education:
        p = para()
        run(p, edu.school, bold=True)
        run(p, f", {edu.location}")
        p = para(after=1)
        run(p, f"{edu.credential}  |  {edu.graduation}")
        if edu.coursework:
            run(para(after=1), "Relevant coursework: " + ", ".join(edu.coursework))

    heading("Experience")
    for tailored_role in tailored.roles:
        r = tailored_role.role
        p = para(before=3, after=1)
        run(p, r.title, bold=True)
        run(p, f"  |  {r.organization}  |  {r.location}  |  {r.start} - {r.end or 'Present'}")
        for b in tailored_role.bullets:
            bullet(b.text)

    if resume.projects:
        heading("Projects")
        for project in resume.projects:
            p = para(before=3, after=1)
            run(p, project.name, bold=True)
            tail = ""
            if project.tech:
                tail += "  |  " + ", ".join(project.tech)
            if project.date:
                tail += f"  |  {project.date}"
            run(p, tail)
            for acc in project.accomplishments:
                bullet(acc.text)

    if resume.skills:
        heading("Technical Skills")
        for label, items in resume.skills.items():
            p = para(after=1)
            run(p, f"{label}: ", bold=True)
            run(p, ", ".join(items))

    doc.save(str(path))
    return path


def slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-").replace("--", "-")


def render(resume: Resume, tailored: TailoredResume, out_dir: Path) -> RenderedDocuments:
    """Render both formats. Filenames carry only the applicant's own name."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{slug(resume.contact.name)}-{slug(tailored.posting.company)}-resume"
    return RenderedDocuments(
        pdf=render_pdf(resume, tailored, out_dir / f"{stem}.pdf"),
        docx=render_docx(resume, tailored, out_dir / f"{stem}.docx"),
    )
