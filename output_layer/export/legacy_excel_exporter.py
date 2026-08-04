# output_layer/export/excel_exporter.py
"""
Exports the seating plan to an Excel workbook (.xlsx).

Sheet 1 – Full Allocation Details (complete, no gaps)
  Sl No | Room | Bench | Stream | Roll No | Register No | Name | Department |
  Semester | Subject Code | Subject Name | Exam Date | Session

Sheet 2 – Attendance Sheet (sorted by dept → roll no, with signature column)

Both sheets are frozen at the header row, colour-coded by stream, and have
auto-fitted column widths.
"""

import logging
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from engine.models.seat_plan import SeatPlan

logger = logging.getLogger(__name__)

# ── Colour palette ────────────────────────────────────────────────────────────
_STREAM_FILL = {
    "A": PatternFill("solid", fgColor="D9EAD3"),   # soft green
    "B": PatternFill("solid", fgColor="CFE2F3"),   # soft blue
    "C": PatternFill("solid", fgColor="FCE5CD"),   # soft orange
}
_HEADER_FILL = PatternFill("solid", fgColor="2C3E50")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
_THIN_BORDER = Border(
    left   = Side(style="thin"),
    right  = Side(style="thin"),
    top    = Side(style="thin"),
    bottom = Side(style="thin"),
)
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_header(ws, columns: list[str]) -> None:
    ws.append(columns)
    for cell in ws[ws.max_row]:
        cell.font      = _HEADER_FONT
        cell.fill      = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border    = _THIN_BORDER


def _style_row(ws, stream: str) -> None:
    fill = _STREAM_FILL.get(stream, PatternFill("solid", fgColor="FFFFFF"))
    for cell in ws[ws.max_row]:
        cell.fill      = fill
        cell.border    = _THIN_BORDER
        cell.alignment = _CENTER


def _auto_width(ws, max_width: int = 40) -> None:
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 3, max_width)


# ── Main exporter ─────────────────────────────────────────────────────────────

class ExcelExporter:
    """
    Usage
    -----
    ExcelExporter().export(seat_plan, "output/seating_plan.xlsx")

    Produces a single .xlsx with two sheets:
      • Full Allocation Details  — every allocated student, one per row,
                                   sorted by Room → Bench → Stream
      • Attendance Sheet         — sorted by Department → Roll No, with
                                   a blank Signature column
    """

    def export(self, plan: SeatPlan, filepath: str | Path) -> None:
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()

        self._write_full_details(wb, plan)
        self._write_attendance(wb, plan)

        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

        wb.save(filepath)
        logger.info(
            "Excel exported → %s  (%d seats, 2 sheets)",
            filepath, len(plan.seats),
        )

    # ── Sheet 1: Full Allocation Details ─────────────────────────────────────

    def _write_full_details(self, wb: openpyxl.Workbook, plan: SeatPlan) -> None:
        ws = wb.create_sheet("Full Allocation Details")

        columns = [
            "Sl No",
            "Room",
            "Bench",
            "Stream",
            "Roll No",          # College roll no  e.g. B23CEA01
            "Register No",      # University reg no e.g. TKM23CE002
            "Name",
            "Department",
            "Semester",
            "Subject Code",
            "Subject Name",
            "Exam Date",
            "Session",
        ]
        _write_header(ws, columns)

        # Sort: Room → Bench No → Stream (A/B/C)
        sorted_seats = sorted(
            plan.seats,
            key=lambda s: (s.classroom.room_no, s.bench_no, s.stream),
        )

        for sl_no, seat in enumerate(sorted_seats, start=1):
            st = seat.student
            ws.append([
                sl_no,
                seat.classroom.room_no,
                seat.bench_no,
                seat.stream,
                st.roll_no,
                st.register_no,
                st.name,
                st.department,
                st.semester,
                st.subject_code,
                st.subject_name,
                st.exam_date,
                st.session,
            ])
            _style_row(ws, seat.stream)

        _auto_width(ws)
        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 20

        logger.info("Sheet 'Full Allocation Details' written (%d rows)", len(sorted_seats))

    # ── Sheet 2: Attendance Sheet ─────────────────────────────────────────────

    def _write_attendance(self, wb: openpyxl.Workbook, plan: SeatPlan) -> None:
        ws = wb.create_sheet("Attendance")

        columns = [
            "Sl No",
            "Roll No",
            "Register No",
            "Name",
            "Department",
            "Room",
            "Bench",
            "Stream",
            "Signature",
        ]
        _write_header(ws, columns)

        # Sort: Department → Roll No (alphabetical, handles B23CEA01 → B23CEA75 correctly)
        sorted_seats = sorted(
            plan.seats,
            key=lambda s: (
                s.student.department,
                s.student.roll_no or s.student.register_no,
            ),
        )

        for sl_no, seat in enumerate(sorted_seats, start=1):
            st = seat.student
            ws.append([
                sl_no,
                st.roll_no,
                st.register_no,
                st.name,
                st.department,
                seat.classroom.room_no,
                seat.bench_no,
                seat.stream,
                "",     # blank for handwritten signature
            ])
            _style_row(ws, seat.stream)

        # Widen the signature column
        ws.column_dimensions["I"].width = 22
        _auto_width(ws, max_width=35)
        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 20

        logger.info("Sheet 'Attendance' written (%d rows)", len(sorted_seats))
