# 0007 — Document rendering stack

**Status:** Accepted
**Date:** 2026-09-15

## Context

A tailored variant has to leave the machine as a file a portal accepts. Two
formats are needed: PDF, which is what most postings ask for, and DOCX, which
some portals parse more reliably than PDF.

Both are read by an ATS before a human sees them, and that parser is the real
audience for the layout.

## Decision

**reportlab** for PDF and **python-docx** for DOCX, rendered from one
`TailoredResume` structure so the two cannot drift apart.

Layout rules are set by what parses, not by what looks clever: single column,
standard section headings, no tables, no text inside graphics, no icon fonts,
embedded standard fonts.

## Why not the alternatives

**LaTeX** produces the best-looking output and was the original resume's
toolchain, but it needs a TeX distribution installed to render — an unreasonable
dependency for a tool that must work from a fresh clone.

**HTML to PDF** (WeasyPrint, headless Chromium) means either a heavy native
dependency stack or a browser, for a one-page document with no layout
complexity.

**Rendering through LibreOffice** was tried first and failed outright in the
build environment — it could not load its own DOCX. A rendering path that
depends on a large external binary is a rendering path that breaks silently.

## Consequences

- Two dependencies, neither with type stubs. mypy overrides are scoped to those
  two modules only, so strict typing still applies everywhere else.
- No system packages. `pip install -e .` is the whole setup.
- Layout is expressed in Python rather than a markup language, which is more
  verbose but keeps a single source for both formats.
- Output is verified by a test that extracts the PDF's text and asserts it comes
  back in the right order — the ATS check, rather than an eyeball check.
