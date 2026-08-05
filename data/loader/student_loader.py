from pathlib import Path
from openpyxl import load_workbook
from engine.models.student import Student


class StudentLoader:
    def __init__(self, student_file: str, timetable_file: str):
        self.student_file = Path(student_file)
        self.timetable_file = Path(timetable_file)

    def load(self) -> list[Student]:
        timetable = self._load_timetable()

        workbook = load_workbook(
            self.student_file,
            data_only=True,
        )

        students: list[Student] = []

        for sheet_name in workbook.sheetnames:

            if sheet_name.lower() == "master overview":
                continue

            worksheet = workbook[sheet_name]

            department = self._get_department(sheet_name)
            semester = self._get_semester(sheet_name)
            section = self._get_section(sheet_name)

            exam = timetable.get((department, semester))

            if exam is None:
                continue

            for row in worksheet.iter_rows(min_row=7, values_only=True):

                if row[0] is None:
                    break

                student = Student(
                    register_no=str(row[3]).strip(),
                    name=str(row[4]).strip(),
                    department=department,
                    semester=semester,
                    section=section,
                    subject_code=exam["subject_code"],
                    subject_name=exam["subject_name"],
                    exam_date=exam["exam_date"],
                    session=exam["session"],
                )

                students.append(student)

        workbook.close()

        return students

    def _load_timetable(self) -> dict:

        workbook = load_workbook(
            self.timetable_file,
            data_only=True,
        )

        worksheet = workbook.active

        timetable = {}

        for row in worksheet.iter_rows(min_row=2, values_only=True):

            department = str(row[5]).strip().upper()
            semester = int(str(row[1]).replace("S", ""))

            timetable[(department, semester)] = {
                "exam_date": row[2],
                "session": row[3],
                "subject_name": row[6],
                "subject_code": row[7],
            }

        workbook.close()

        return timetable

    @staticmethod
    def _get_department(sheet_name: str) -> str:
        return sheet_name.split()[0].upper()

    @staticmethod
    def _get_semester(sheet_name: str) -> int:
        start = sheet_name.find("(S")
        end = sheet_name.find(")", start)
        return int(sheet_name[start + 2:end])

    @staticmethod
    def _get_section(sheet_name: str) -> str:

        parts = sheet_name.split()

        if len(parts) >= 3 and parts[-2].startswith("(S") is False:
            return parts[-2]

        return "A"