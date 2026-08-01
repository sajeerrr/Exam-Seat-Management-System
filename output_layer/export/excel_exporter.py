# output_layer/export/excel_exporter.py
"""
Exports the seating plan to an Excel workbook (.xlsx).

Produces two sheets:
  1. Seating Plan   – Room | Bench | Stream | Register No | Name | Dept
  2. Attendance     – Register No | Name | Department | Bench | Stream | Room | Signature
"""

import logging
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from engine.models.seat_plan import SeatPlan

logger = logging.getLogger(__name__)

_STREAM_COLOURS = {
    "A": "D9EAD3",   # green
    "B": "CFE2F3",   # blue
    "C": "FCE5CD",   # orange
}

_HEADER_FILL  = PatternFill("solid", fgColor="4A4A4A")
_HEADER_FONT  = Font(bold=True, color="FFFFFF")
_THIN_BORDER  = Border(
    left   = Side(style="thin"),
    right  = Side(style="thin"),
    top    = Side(style="thin"),
    bottom = Side(style="thin"),
)


def _write_header(ws, columns: list[str]) -> None:
    ws.append(columns)
    for cell in ws[ws.max_row]:
        cell.font      = _HEADER_FONT
        cell.fill      = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border    = _THIN_BORDER


def _auto_width(ws) -> None:
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 40)


class ExcelExporter:
    """
    Usage
    -----
    ExcelExporter().export(seat_plan, "output/seating_plan.xlsx")
    """

    def export(self, plan: SeatPlan, filepath: str | Path) -> None:
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()
        self._write_seating_sheet(wb, plan)
        self._write_attendance_sheet(wb, plan)

        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

        wb.save(filepath)
        logger.info("Excel exported → %s  (%d seats)", filepath, len(plan.seats))

    def _write_seating_sheet(self, wb: openpyxl.Workbook, plan: SeatPlan) -> None:
        ws = wb.create_sheet("Seating Plan")
        _write_header(ws, ["Room", "Bench", "Stream", "Register No", "Name", "Department"])

        for seat in sorted(plan.seats, key=lambda s: (s.classroom.room_no, s.bench_no, s.stream)):
            fill_colour = _STREAM_COLOURS.get(seat.stream, "FFFFFF")
            ws.append([
                seat.classroom.room_no,
                seat.bench_no,
                seat.stream,
                seat.student.register_no,
                seat.student.name,
                seat.student.department,
            ])
            row = ws[ws.max_row]
            stream_fill = PatternFill("solid", fgColor=fill_colour)
            for cell in row:
                cell.fill      = stream_fill
                cell.border    = _THIN_BORDER
                cell.alignment = Alignment(horizontal="center")

        _auto_width(ws)
        ws.freeze_panes = "A2"

    def _write_attendance_sheet(self, wb: openpyxl.Workbook, plan: SeatPlan) -> None:
        ws = wb.create_sheet("Attendance")
        _write_header(ws, [
            "Register No", "Name", "Department",
            "Room", "Bench", "Stream", "Signature"
        ])

        for seat in sorted(plan.seats, key=lambda s: (s.student.department, s.student.register_no)):
            ws.append([
                seat.student.register_no,
                seat.student.name,
                seat.student.department,
                seat.classroom.room_no,
                seat.bench_no,
                seat.stream,
                "",
            ])
            row = ws[ws.max_row]
            for cell in row:
                cell.border    = _THIN_BORDER
                cell.alignment = Alignment(horizontal="center")

        ws.column_dimensions["G"].width = 20
        _auto_width(ws)
        ws.freeze_panes = "A2"
