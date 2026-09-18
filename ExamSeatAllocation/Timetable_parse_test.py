"""
test_timetable_parser.py

Run this from the Django project directory after placing the parser in the
same package as the other parsers.

Examples:

    python test_timetable_parser.py /path/to/timetable.pdf

Or, if the parser is inside a Django app:

    python manage.py shell
    >>> exec(open("test_timetable_parser.py").read())

The script also works directly with:
    python test_timetable_parser.py
by using the default PDF paths below.
"""

from pathlib import Path
import sys

# ---------------------------------------------------------------------------
# CHANGE THIS IMPORT if timetable_parser.py lives somewhere else.
# Example:
#   from ExamSeatAllocation.parsers.timetable_parser import parse_timetable_pdf
# ---------------------------------------------------------------------------
from exam_allocator.parsers.timetable_parser import parse_timetable_pdf


DEFAULT_FILES = [
    # Change these to your local timetable PDF paths.
    "/home/petercj/Documents/Dev/Mini_project/resources/inputs/timetable1.pdf"
]


def print_result(pdf_path: str) -> None:
    print("\n" + "=" * 90)
    print(f"FILE: {pdf_path}")
    print("=" * 90)

    try:
        result = parse_timetable_pdf(pdf_path)
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        return

    print("\nMETADATA")
    print("-" * 90)
    if result.metadata:
        for key, value in result.metadata.items():
            print(f"{key:15}: {value}")
    else:
        print("No metadata extracted.")

    print("\nEXAMS")
    print("-" * 90)

    if not result.exams:
        print("No exams extracted.")
    else:
        for number, exam in enumerate(result.exams, start=1):
            print(
                f"{number:2}. "
                f"{exam.exam_date:%d-%m-%Y} | "
                f"{exam.session} | "
                f"{exam.slot:<3} | "
                f"{exam.subject_code or '[NO CODE]':<12} | "
                f"{exam.subject_name} | "
                f"{exam.duration} min"
            )

    print("\nISSUES")
    print("-" * 90)

    if not result.issues:
        print("No issues found.")
    else:
        for issue in result.issues:
            location = f"page {issue.page_number}"
            if issue.table_index is not None:
                location += f", table {issue.table_index}"
            print(f"- [{issue.issue_type}] {location}: {issue.detail}")

    print("\nSUMMARY")
    print("-" * 90)
    print(f"Exams extracted : {len(result.exams)}")
    print(f"Issues found    : {len(result.issues)}")


def main() -> None:
    # Only treat command-line arguments ending in .pdf as input files.
    # This prevents Django's "shell" argument from being interpreted
    # as a PDF filename.
    files = [
        arg for arg in sys.argv[1:]
        if arg.lower().endswith(".pdf")
    ]

    if not files:
        files = DEFAULT_FILES

    for pdf_path in files:
        print_result(pdf_path)


if __name__ == "__main__":
    main()