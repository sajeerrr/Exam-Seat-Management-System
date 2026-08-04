"""
demo/run_demo.py
================
TKM College of Engineering — Exam Seat Management pipeline.

Run from the project root:
    python -m demo.run_demo

Steps
-----
1.  Parse consolidated student Excel (resources/)  → Student objects
2.  Parse classroom list (resources/class.xlsx)    → Classroom list
3.  Parse ALL timetable PDFs in resources/         → ExamSession list
4.  Show available exam slots; user picks one
5.  Filter + stamp students for selected slot
6.  Build groups
7.  Run allocation engine
8.  Print allocation report + statistics
9.  Export output/master_<date>_<session>.xlsx
"""

import logging
import sys
import io
from pathlib import Path

# Force UTF-8 so box-drawing chars don't crash on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Logging ────────────────────────────────────────────────────────────────────
from engine.config import LOG_FORMAT
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# ── I/O Layer ──────────────────────────────────────────────────────────────────
from io_layer.input.excel_student_parser import ExcelStudentParser
from io_layer.input.classroom_parser     import ClassroomParser
from io_layer.input.timetable_parser     import TimetableParser
from io_layer.input.session_filter    import SessionFilter
from io_layer.repositories.student_repository   import StudentRepository
from io_layer.repositories.classroom_repository import ClassroomRepository

# ── Engine ─────────────────────────────────────────────────────────────────────
from engine.builders.group_builder      import GroupBuilder
from engine.context.allocation_context  import AllocationContext
from engine.models.remaining_pool       import RemainingPool
from engine.services.allocation_service import AllocationService

# ── Output Layer ───────────────────────────────────────────────────────────────
from output_layer.reports.allocation_report     import AllocationReport
from output_layer.reports.allocation_statistics import AllocationStatistics
from output_layer.export.master_sheet_exporter  import MasterSheetExporter


# ══════════════════════════════════════════════════════════════════════════════
# Paths & constants
# ══════════════════════════════════════════════════════════════════════════════

RESOURCES_DIR    = Path("resources")
OUTPUT_DIR       = Path("output")
CLASSROOM_EXCEL  = RESOURCES_DIR / "class.xlsx"
STUDENT_EXCEL    = RESOURCES_DIR / "TKMCE_All_Classes_Separate_Student_Lists.xlsx"

EXAM_INFO_BASE = {
    "college_name": "TKM College of Engineering, Kollam-5",
    "exam_name":    "Second Series Exam, March 2026",
}

# Keywords that identify timetable PDFs (vs. student PDFs)
_TIMETABLE_KEYWORDS = ["exam", "series", "timetable", "time table", "revised"]


def _is_timetable_pdf(path: Path) -> bool:
    return any(kw in path.name.lower() for kw in _TIMETABLE_KEYWORDS)


# ══════════════════════════════════════════════════════════════════════════════
def main():
    logger.info("━━━━  TKM Exam Seat Management  ━━━━")

    # ── Step 1: Parse consolidated student Excel ──────────────────────────────
    logger.info("Step 1: Parsing student Excel …")
    if not STUDENT_EXCEL.exists():
        logger.error("Student Excel not found: %s — aborting.", STUDENT_EXCEL)
        sys.exit(1)
    all_students = ExcelStudentParser().parse(STUDENT_EXCEL)
    if not all_students:
        logger.error("No students parsed from %s — aborting.", STUDENT_EXCEL)
        sys.exit(1)
    student_repo = StudentRepository()
    student_repo.load(all_students)
    logger.info("  → %d students loaded", student_repo.count())

    # ── Step 2: Parse classrooms ────────────────────────────────────────────────
    logger.info("Step 2: Parsing classroom list …")
    if not CLASSROOM_EXCEL.exists():
        logger.error("Classroom file not found: %s", CLASSROOM_EXCEL)
        sys.exit(1)
    classrooms = ClassroomParser().parse(CLASSROOM_EXCEL)
    classroom_repo = ClassroomRepository()
    classroom_repo.load(classrooms)
    logger.info("  → %d classrooms loaded", classroom_repo.count())

    # ── Step 3: Parse ALL timetable PDFs ────────────────────────────────────────
    logger.info("Step 3: Parsing all timetable PDFs …")
    timetable_pdfs = sorted(
        f for f in RESOURCES_DIR.iterdir()
        if f.suffix.lower() == ".pdf" and _is_timetable_pdf(f)
    )
    if not timetable_pdfs:
        logger.error("No timetable PDFs found in %s — aborting.", RESOURCES_DIR)
        sys.exit(1)

    parser = TimetableParser()
    all_sessions = []
    for pdf in timetable_pdfs:
        sessions = parser.parse(pdf)
        logger.info("    %s  →  %d sessions", pdf.name, len(sessions))
        all_sessions.extend(sessions)
    logger.info("  → %d total exam sessions parsed", len(all_sessions))

    # ── Step 4: Interactive slot selection ──────────────────────────────────────
    slots = sorted(set((s.exam_date, s.session) for s in all_sessions))

    print("\nAvailable exam slots:")
    for i, (date, session) in enumerate(slots, 1):
        depts = sorted(set(
            s.department for s in all_sessions
            if s.exam_date == date and s.session == session
        ))
        print(f"  {i:2d}.  {date}  {session}   → {', '.join(depts)}")

    while True:
        try:
            choice = int(input("\nEnter slot number: ").strip()) - 1
            if 0 <= choice < len(slots):
                break
            print(f"  Please enter a number between 1 and {len(slots)}.")
        except (ValueError, KeyboardInterrupt):
            print("Cancelled.")
            sys.exit(0)

    exam_date, exam_session = slots[choice]
    logger.info("Selected: %s %s", exam_date, exam_session)

    # ── Step 5: Filter students for selected slot ───────────────────────────────
    logger.info("Step 5: Filtering students for %s %s …", exam_date, exam_session)
    sitting_students = SessionFilter().filter(
        students  = student_repo.get_all(),
        sessions  = all_sessions,
        exam_date = exam_date,
        session   = exam_session,
    )
    logger.info("  → %d students sitting this slot", len(sitting_students))

    if not sitting_students:
        logger.error(
            "No students found for %s %s. "
            "Check that timetable dept codes match student PDF dept codes.",
            exam_date, exam_session,
        )
        sys.exit(1)

    # ── Step 6: Build groups ────────────────────────────────────────────────────
    logger.info("Step 6: Building groups …")
    groups = GroupBuilder().build(sitting_students)
    for g in groups:
        logger.info("  Group %-40s  %d students", g.group_id, g.strength)

    # ── Step 7: Allocation ──────────────────────────────────────────────────────
    logger.info("Step 7: Running allocation engine …")
    context = AllocationContext(
        groups           = groups,
        room_allocations = classroom_repo.get_room_allocations(),
        remaining_pool   = RemainingPool(),
    )
    context, plan = AllocationService().execute(context)
    logger.info("  → Allocation complete. %d seats generated.", len(plan.seats))

    # ── Step 8: Report + Statistics ─────────────────────────────────────────────
    logger.info("Step 8: Generating allocation report …")
    print(AllocationReport().generate(context))

    logger.info("Step 8b: Computing statistics …")
    AllocationStatistics().compute(
        context, students_loaded=len(sitting_students)
    ).print_summary()

    # ── Step 9: Export Master Sheet Excel ───────────────────────────────────────
    logger.info("Step 9: Exporting Master Sheet Excel …")
    exam_info  = {**EXAM_INFO_BASE, "exam_date": exam_date, "session": exam_session}
    excel_path = OUTPUT_DIR / f"master_{exam_date}_{exam_session}.xlsx"
    MasterSheetExporter().export(
        context    = context,
        classrooms = classrooms,
        exam_info  = exam_info,
        filepath   = excel_path,
    )
    logger.info("  → Saved: %s", excel_path)

    logger.info("━━━━  Done  ━━━━")


if __name__ == "__main__":
    main()
