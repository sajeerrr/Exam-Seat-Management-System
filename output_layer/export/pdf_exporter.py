# output_layer/export/pdf_exporter.py
"""
Exports the seating plan to a PDF file using fpdf2.

Layout: one table per room, one row per seat.
  Room 101
  Bench | Stream A (Reg No / Name)  | Stream B (Reg No / Name)  | Stream C (Reg No / Name)
    1   |  TKM23CE002 / AAMI S NATH | TKM23ME004 / ALEX K       | TKM23CS001 / ARJUN P
    2   |  ...
"""

import logging
from collections import defaultdict
from pathlib import Path

from fpdf import FPDF

from engine.models.seat_plan import SeatPlan
from engine.models.seat import Seat

logger = logging.getLogger(__name__)


class _PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 8, "TKM COLLEGE OF ENGINEERING — EXAM SEATING PLAN", align="C")
        self.ln(10)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 5, f"Page {self.page_no()}", align="C")


class PDFExporter:
    """
    Usage
    -----
    PDFExporter().export(seat_plan, "output/seating_plan.pdf")
    """

    def export(self, plan: SeatPlan, filepath: str | Path) -> None:
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        rooms: dict[str, dict[int, dict[str, Seat]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        for seat in plan.seats:
            rooms[seat.classroom.room_no][seat.bench_no][seat.stream] = seat

        pdf = _PDF(orientation="L", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_margins(10, 15, 10)

        for room_no, benches in sorted(rooms.items()):
            pdf.add_page()
            self._write_room(pdf, room_no, benches)

        pdf.output(str(filepath))
        logger.info("PDF exported → %s  (%d rooms)", filepath, len(rooms))

    def _write_room(
        self,
        pdf: _PDF,
        room_no: str,
        benches: dict[int, dict[str, Seat]],
    ) -> None:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, f"Room: {room_no}", ln=True)
        pdf.ln(2)

        pdf.set_font("Helvetica", "B", 8)
        col_w   = 87
        bench_w = 15

        pdf.set_fill_color(60, 60, 60)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(bench_w, 7, "Bench", border=1, align="C", fill=True)
        for stream in ["A", "B", "C"]:
            pdf.cell(col_w, 7, f"Stream {stream}", border=1, align="C", fill=True)
        pdf.ln()

        stream_colours = {
            "A": (217, 234, 211),
            "B": (207, 226, 243),
            "C": (252, 229, 205),
        }

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 8)

        for bench_no in sorted(benches.keys()):
            pdf.cell(bench_w, 6, str(bench_no), border=1, align="C")
            for stream in ["A", "B", "C"]:
                seat = benches[bench_no].get(stream)
                if seat:
                    r, g, b = stream_colours[stream]
                    pdf.set_fill_color(r, g, b)
                    text = f"{seat.student.register_no}  {seat.student.name}"
                    pdf.cell(col_w, 6, text[:48], border=1, fill=True)
                else:
                    pdf.cell(col_w, 6, "—", border=1, align="C")
            pdf.ln()

        pdf.ln(5)
