"""
demo/run_demo.py
================
End-to-end demonstration of the full Exam Seat Management pipeline.

Run from the project root:
    python -m demo.run_demo

What it does
------------
1.  Parse all student PDFs in resources/
2.  Parse the classroom list Excel
3.  Parse the timetable PDF
4.  Filter students for a chosen exam slot (date + session)
5.  Build groups automatically
6.  Run the allocation engine (Primary → Remaining → Validate → Seat plan)
7.  Print the allocation report
8.  Print allocation statistics
9.  Export Excel seating plan  → output/seating_plan.xlsx
10. Export PDF seating plan    → output/seating_plan.pdf
"""

import logging
import sys
import io
from pathlib import Path

# Force UTF-8 output so box-drawing chars in the report don't crash on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Logging ────────────────────────────────────────────────────────────────
from engine.config import LOG_FORMAT
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# ── I/O Layer ──────────────────────────────────────────────────────────────
from io_layer.input.pdf_parser        import MultiplePDFParser
from io_layer.input.classroom_parser  import ClassroomParser
from io_layer.input.timetable_parser  import TimetableParser
from io_layer.input.session_filter    import SessionFilter
from io_layer.repositories.student_repository   import StudentRepository
from io_layer.repositories.classroom_repository import ClassroomRepository

# ── Engine ─────────────────────────────────────────────────────────────────
from engine.builders.group_builder      import GroupBuilder
from engine.context.allocation_context  import AllocationContext
from engine.models.remaining_pool       import RemainingPool
from engine.services.allocation_service import AllocationService

# ── Output Layer ───────────────────────────────────────────────────────────
from output_layer.reports.allocation_report     import AllocationReport
from output_layer.reports.allocation_statistics import AllocationStatistics
from output_layer.export.excel_exporter         import ExcelExporter
from output_layer.export.pdf_exporter           import PDFExporter


# ══════════════════════════════════════════════════════════════════════════════
# Configuration — change these to run for a different exam slot
# ══════════════════════════════════════════════════════════════════════════════

RESOURCES_DIR   = Path("resources")
OUTPUT_DIR      = Path("output")

EXAM_DATE       = "12-03-2026"   # DD-MM-YYYY
EXAM_SESSION    = "FN"           # FN or AN

TIMETABLE_PDF   = RESOURCES_DIR / "2 S6 B Tech 2nd Series Exam- March 2026 -  Revised.pdf"
CLASSROOM_EXCEL = RESOURCES_DIR / "Classroom List.xlsx"


# ══════════════════════════════════════════════════════════════════════════════
def main():
    logger.info("━━━━  Exam Seat Management Demo  ━━━━")

    # ── Step 1: Parse student PDFs ─────────────────────────────────────────
    logger.info("Step 1: Parsing student PDFs …")
    all_students = MultiplePDFParser().parse_directory(RESOURCES_DIR)

    student_repo = StudentRepository()
    student_repo.load(all_students)
    logger.info("  → %d students loaded", student_repo.count())

    # ── Step 2: Parse classrooms ───────────────────────────────────────────
    logger.info("Step 2: Parsing classroom list …")
    classrooms = ClassroomParser().parse(CLASSROOM_EXCEL)

    classroom_repo = ClassroomRepository()
    classroom_repo.load(classrooms)
    logger.info("  → %d classrooms loaded", classroom_repo.count())

    # ── Step 3: Parse timetable ────────────────────────────────────────────
    logger.info("Step 3: Parsing timetable …")
    sessions = TimetableParser().parse(TIMETABLE_PDF)
    logger.info("  → %d exam sessions parsed", len(sessions))

    # ── Step 4: Filter students for this exam slot ─────────────────────────
    logger.info("Step 4: Filtering for %s %s …", EXAM_DATE, EXAM_SESSION)
    sitting_students = SessionFilter().filter(
        students  = student_repo.get_all(),
        sessions  = sessions,
        exam_date = EXAM_DATE,
        session   = EXAM_SESSION,
    )
    logger.info("  → %d students sitting this slot", len(sitting_students))

    if not sitting_students:
        logger.error("No students found for %s %s — check timetable or date.", EXAM_DATE, EXAM_SESSION)
        sys.exit(1)

    # ── Step 5: Build groups ───────────────────────────────────────────────
    logger.info("Step 5: Building groups …")
    groups = GroupBuilder().build(sitting_students)
    for g in groups:
        logger.info("  Group %-30s  %d students", g.group_id, g.strength)

    # ── Step 6: Allocation ─────────────────────────────────────────────────
    logger.info("Step 6: Running allocation engine …")
    context = AllocationContext(
        groups           = groups,
        room_allocations = classroom_repo.get_room_allocations(),
        remaining_pool   = RemainingPool(),
    )

    context, plan = AllocationService().execute(context)
    logger.info("  → Allocation complete. %d seats generated.", len(plan.seats))

    # ── Step 7: Report ─────────────────────────────────────────────────────
    logger.info("Step 7: Generating allocation report …")
    print(AllocationReport().generate(context))

    # ── Step 8: Statistics ─────────────────────────────────────────────────
    logger.info("Step 8: Computing statistics …")
    AllocationStatistics().compute(context, students_loaded=len(sitting_students)).print_summary()

    # ── Step 9: Excel export ───────────────────────────────────────────────
    logger.info("Step 9: Exporting Excel …")
    excel_path = OUTPUT_DIR / f"seating_plan_{EXAM_DATE}_{EXAM_SESSION}.xlsx"
    ExcelExporter().export(plan, excel_path)
    logger.info("  → Saved: %s", excel_path)

    # ── Step 10: PDF export ────────────────────────────────────────────────
    logger.info("Step 10: Exporting PDF …")
    pdf_path = OUTPUT_DIR / f"seating_plan_{EXAM_DATE}_{EXAM_SESSION}.pdf"
    PDFExporter().export(plan, pdf_path)
    logger.info("  → Saved: %s", pdf_path)

    logger.info("━━━━  Done  ━━━━")


if __name__ == "__main__":
    main()
