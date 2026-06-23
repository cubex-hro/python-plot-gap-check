#!/usr/bin/env python3
"""
PDF gap check
======================
Analyzes a PDF for excessively narrow gaps (< 1 mm) and fonts that are too small (recommended: < 6 pt).
Creates an annotated PDF copy with color-coded markings.

Use:
    python gap_check.py input.pdf [--min-gap 1.0] [--min-font 6.0]
"""

import sys
import argparse
import fitz  # PyMuPDF
from itertools import combinations
from pathlib import Path


# ── Configurable thresholds ────────────────────────────────────────────
DEFAULT_MIN_GAP_MM    = 1.0   # Minimum gap in mm between contours
DEFAULT_MIN_FONT_PT   = 6.0   # Minimum font size in points
MM_TO_PT              = 72 / 25.4  # 1 mm in points


# ── Colors ───────────────────────────────────────────────────────────────────
RED    = (1, 0, 0)
ORANGE = (1, 0.5, 0)
YELLOW = (1, 1, 0)


def mm_to_pt(mm: float) -> float:
    return mm * MM_TO_PT


def rect_gap(r1: fitz.Rect, r2: fitz.Rect) -> float:
    """Minimum gap (in points) between two rectangles."""
    dx = max(0, max(r1.x0, r2.x0) - min(r1.x1, r2.x1))
    dy = max(0, max(r1.y0, r2.y0) - min(r1.y1, r2.y1))
    return (dx**2 + dy**2) ** 0.5


def check_page(page: fitz.Page, min_gap_pt: float, min_font_pt: float):
    """
    Returns:
        gap_issues   – List of (rect1, rect2, gap_pt) for gaps that are too small
        font_issues  – List of (rect, font_size) for fonts that are too small
    """
    gap_issues  = []
    font_issues = []

    # ── 1. Vector paths (outlines) ────────────────────────────────────────────
    paths = page.get_drawings()
    rects = []
    for p in paths:
        r = p["rect"]
        if r.width > 0.5 and r.height > 0.5:   # Ignore points/hairlines
            rects.append(r)

    # Bridge check: every pair of contour bounding boxes
    # Limit to a representative sample if there are very many paths
    if len(rects) > 300:
        # Proximity-based clustering: check neighbors only (simplified via sorting)
        rects_sorted = sorted(rects, key=lambda r: r.x0)
        pairs_to_check = []
        for i, r in enumerate(rects_sorted):
            for j in range(i + 1, min(i + 20, len(rects_sorted))):
                pairs_to_check.append((rects_sorted[i], rects_sorted[j]))
    else:
        pairs_to_check = list(combinations(rects, 2))

    for r1, r2 in pairs_to_check:
        gap = rect_gap(r1, r2)
        if 0 < gap < min_gap_pt:
            gap_issues.append((r1, r2, gap))

    # ── 2. Text elements ─────────────────────────────────────────────────────
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    for block in blocks:
        if block["type"] != 0:   # Text blocks only
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                size = span["size"]
                if size < min_font_pt:
                    bbox = fitz.Rect(span["bbox"])
                    font_issues.append((bbox, size, span["text"][:40]))

    return gap_issues, font_issues


def annotate_pdf(input_path: str, output_path: str,
                 min_gap_mm: float = DEFAULT_MIN_GAP_MM,
                 min_font_pt: float = DEFAULT_MIN_FONT_PT):

    min_gap_pt = mm_to_pt(min_gap_mm)
    doc = fitz.open(input_path)

    total_gaps  = 0
    total_fonts = 0

    print(f"\n📄  File       : {input_path}")
    print(f"📐  Min. gab   : {min_gap_mm} mm  ({min_gap_pt:.2f} pt)")
    print(f"🔤  Min. font   : {min_font_pt} pt")
    print(f"📃  Pages      : {doc.page_count}\n")

    for pno in range(doc.page_count):
        page = doc[pno]
        pno += 1
        gap_issues, font_issues = check_page(page, min_gap_pt, min_font_pt)

        # ── Mark gap problems ──────────────────────────────────────────
        for r1, r2, gap_pt in gap_issues:
            total_gaps += 1
            gap_mm = gap_pt / MM_TO_PT
            # Connecting line between the centers
            c1 = ((r1.x0 + r1.x1) / 2, (r1.y0 + r1.y1) / 2)
            c2 = ((r2.x0 + r2.x1) / 2, (r2.y0 + r2.y1) / 2)
            annot = page.add_line_annot(c1, c2)
            annot.set_colors(stroke=RED)
            annot.set_border(width=1.5)
            annot.set_info(content=f"Steg zu klein: {gap_mm:.2f} mm (min. {min_gap_mm} mm)")
            annot.update()

            # Highlight box around both objects
            combined = r1 | r2   # Union-Rect
            expanded = combined + (-3, -3, 3, 3)
            annot2 = page.add_rect_annot(expanded)
            annot2.set_colors(stroke=RED, fill=YELLOW)
            annot2.set_opacity(0.25)
            annot2.set_info(content=f"Steg zu klein: {gap_mm:.2f} mm")
            annot2.update()

        # ── Mark font problems ───────────────────────────────────────
        for bbox, size, text in font_issues:
            total_fonts += 1
            expanded = bbox + (-2, -2, 2, 2)
            annot = page.add_rect_annot(expanded)
            annot.set_colors(stroke=ORANGE, fill=ORANGE)
            annot.set_opacity(0.35)
            annot.set_info(content=f"Schrift zu klein: {size:.1f} pt  |  \"{text}\"")
            annot.update()

        print(f"  Page {pno:3d}: {len(gap_issues):3d} gap-problems  |  {len(font_issues):3d} font-problems")

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()

    print(f"\n✅  Overall gab-problems  : {total_gaps}")
    print(f"✅  Overall font-problems   : {total_fonts}")
    print(f"\n💾  Output saved  : {output_path}\n")

    if total_gaps == 0 and total_fonts == 0:
        print("🎉  No problems found – file should be printable.\n")
    else:
        print("⚠️   Please check and adjust the marked sections in the output PDF..\n")


def main():
    parser = argparse.ArgumentParser(
        description="Checks the PDF for to small gaps and fonts that are too small for plotter vinyl."
    )
    parser.add_argument("input", help="Input-PDF")
    parser.add_argument(
        "--min-gap", type=float, default=DEFAULT_MIN_GAP_MM,
        help=f"Minimum gap in mm (Standard: {DEFAULT_MIN_GAP_MM})"
    )
    parser.add_argument(
        "--min-font", type=float, default=DEFAULT_MIN_FONT_PT,
        help=f"Minimum Font in pt (Standard: {DEFAULT_MIN_FONT_PT})"
    )
    args = parser.parse_args()

    input_path  = args.input
    output_path = str(Path(input_path).stem) + "_proof.pdf"

    annotate_pdf(input_path, output_path,
                 min_gap_mm=args.min_gap,
                 min_font_pt=args.min_font)


if __name__ == "__main__":
    main()