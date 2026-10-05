"""
Unit and integration tests for multi-file timetable loader and parser.
"""

from datetime import date
from pathlib import Path
import unittest

from exam_allocator.parsers.multi_timetable_loader import (
    discover_timetable_files,
    parse_all_timetables,
    _detect_programme_semester,
    ExamRecord,
)


class TestMultiTimetableLoader(unittest.TestCase):

    def test_discover_files(self):
        files = discover_timetable_files()
        self.assertIsInstance(files, list)

    def test_detect_programme_semester(self):
        prog, sem = _detect_programme_semester("B Tech - S8 - 2nd Series Exam - March 2026", "BTech_S8_Timetable.xlsx")
        self.assertEqual(prog, "B.Tech")
        self.assertEqual(sem, 8)

        prog2, sem2 = _detect_programme_semester("B Arch - S4 - 2nd Series Exam - March 2026", "BArch_S4.pdf")
        self.assertEqual(prog2, "B.Arch")
        self.assertEqual(sem2, 4)

    def test_parse_all_timetables_execution(self):
        result = parse_all_timetables()
        self.assertGreaterEqual(result.files_discovered, 1)
        self.assertIsInstance(result.merged_exams, list)
        self.assertIsInstance(result.summary_by_programme_semester, dict)
        self.assertGreaterEqual(result.total_records, 1)

    def test_exam_record_duplicate_key(self):
        e1 = ExamRecord(
            programme="B.Tech",
            semester=6,
            exam_date=date(2026, 3, 12),
            session="FN",
            time="10:00 - 12:00",
            branch="CE",
            branches=["CE"],
            subject_name="Quantity Surveying",
            subject_code="22CET801",
            duration_minutes=120,
            source_file="file1.xlsx"
        )
        e2 = ExamRecord(
            programme="B.Tech",
            semester=6,
            exam_date=date(2026, 3, 12),
            session="fn",
            time="10:00 - 12:00",
            branch="CE",
            branches=["CE"],
            subject_name="Quantity Surveying",
            subject_code="22CET801",
            duration_minutes=120,
            source_file="file2.xlsx"
        )
        self.assertEqual(e1.duplicate_key(), e2.duplicate_key())


if __name__ == "__main__":
    unittest.main()
