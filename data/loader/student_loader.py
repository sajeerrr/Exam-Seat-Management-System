from pathlib import Path
from openpyxl import load_workbook
from engine.models.student import Student


class StudentLoader:
    def __init__(self, student_file: str, timetable_file: str):
        self.student_file = Path(student_file)
        self.timetable_file = Path(timetable_file)

    def load(self) -> list[Student]:
        timetable = self._load_timetable()
        workbook = load_workbook(self.student_file, data_only=True)
        students: list[Student] = []

        for sheet_name in workbook.sheetnames:
            if sheet_name.lower() == "master overview":
                continue

            worksheet = workbook[sheet_name]
            department = self._get_department(sheet_name)
            semester = self._get_semester(worksheet, sheet_name)
            section = self._get_section(sheet_name)

            exams = timetable.get((department, semester), [])
            if not exams:
                continue

            for row in worksheet.iter_rows(min_row=2, values_only=True):
                if row[0] is None:
                    break

                roll_no = str(row[6]).strip() if len(row) > 6 and row[6] else ""
                base_reg_no = str(row[7]).strip() if len(row) > 7 and row[7] else ""
                name = str(row[8]).strip() if len(row) > 8 and row[8] else ""
                if not base_reg_no or base_reg_no.lower() == "none":
                    continue

                # Disambiguate registration numbers for multi-section classes
                reg_no = f"{base_reg_no}-{section}" if section else base_reg_no

                for exam in exams:
                    code = str(exam["subject_code"] or "").strip()
                    subj_name = str(exam["subject_name"] or "").strip()

                    # Skip elective courses to prevent adjacent column clash issues
                    if "elective" in code.lower() or "elective" in subj_name.lower():
                        continue

                    students.append(
                        Student(
                            register_no=reg_no,
                            name=name,
                            department=department,
                            semester=semester,
                            section=section,
                            subject_code=code if code and code.lower() != "nan" else subj_name,
                            subject_name=subj_name,
                            exam_date=str(exam["exam_date"] or "").strip(),
                            session=str(exam["session"] or "").strip(),
                            roll_no=roll_no,
                        )
                    )

        workbook.close()
        return students

    def _load_timetable(self) -> dict[tuple[str, int], list[dict]]:
        workbook = load_workbook(self.timetable_file, data_only=True)
        timetable: dict[tuple[str, int], list[dict]] = {}
        all_btech_depts = ["CE", "ME", "EE", "EC", "CS", "CH", "EL"]

        for sheet_name in workbook.sheetnames:
            worksheet = workbook[sheet_name]
            import re
            is_barch = "BArch" in sheet_name or "B.Arch" in sheet_name

            for row in worksheet.iter_rows(min_row=2, values_only=True):
                if row[0] is None:
                    continue

                date_val = row[0]
                if hasattr(date_val, "strftime"):
                    exam_date_str = date_val.strftime("%d-%m-%Y")
                else:
                    exam_date_str = str(date_val).strip()

                session = str(row[2]).strip() if row[2] else ""

                if is_barch:
                    branch_raw = "B.ARCH"
                    sem_col = str(row[4]).strip() if row[4] else ""
                    m_sem = re.search(r'S(\d)', sem_col, re.IGNORECASE)
                    semester = int(m_sem.group(1)) if m_sem else 4
                    subject_code = str(row[6]).strip() if len(row) > 6 and row[6] else ""
                    subject_name = str(row[7]).strip() if len(row) > 7 and row[7] else ""
                else:
                    if row[4] is None:
                        continue
                    branch_raw = str(row[4]).strip().upper()
                    subject_code = str(row[5]).strip() if len(row) > 5 and row[5] else ""
                    subject_name = str(row[6]).strip() if len(row) > 6 and row[6] else ""

                    semester = 4
                    m_sem = re.search(r'[A-Z]{2,3}[A-Z]?(\d)', subject_code)
                    if m_sem:
                        semester = int(m_sem.group(1))
                    else:
                        m_sheet_sem = re.search(r'S(\d)', sheet_name)
                        if m_sheet_sem:
                            semester = int(m_sheet_sem.group(1))

                if branch_raw == "B ARCH" or branch_raw == "B.ARCH":
                    target_depts = ["B.ARCH"]
                elif branch_raw == "ALL BRANCHES":
                    target_depts = all_btech_depts
                elif "/" in branch_raw or "," in branch_raw:
                    import re
                    target_depts = [b.strip() for b in re.split(r'[/,]+', branch_raw) if b.strip()]
                else:
                    target_depts = [branch_raw]

                exam_data = {
                    "exam_date": exam_date_str,
                    "session": session,
                    "subject_name": subject_name,
                    "subject_code": subject_code,
                }

                for dept in target_depts:
                    key = (dept, semester)
                    if key not in timetable:
                        timetable[key] = []
                    timetable[key].append(exam_data)

        workbook.close()
        return timetable

    @staticmethod
    def _get_department(sheet_name: str) -> str:
        raw = sheet_name.split()[0].upper().replace(".", "")
        if raw == "BARCH": return "B.ARCH"
        if raw in ["EEE", "EE"]: return "EE"
        if raw in ["ECE", "EC"]: return "EC"
        if raw in ["CSE", "CS"]: return "CS"
        if raw in ["CHE", "CH"]: return "CH"
        return raw

    @staticmethod
    def _get_semester(worksheet, sheet_name: str) -> int:
        import re
        # 1. Try extracting from sheet name if format has (S...) or S<digit>
        match = re.search(r'\(S(\d+)\)', sheet_name)
        if match:
            return int(match.group(1))
        match_s = re.search(r'\bS(\d+)\b', sheet_name, re.IGNORECASE)
        if match_s:
            return int(match_s.group(1))

        # 2. Try parsing from worksheet cell D2 (or row 2, col 4) where semester is often specified (e.g. 'VIIIth Semester')
        cell_val = worksheet.cell(2, 4).value if worksheet.max_row >= 2 else None
        if cell_val is not None:
            sem_str = str(cell_val).strip()
            if sem_str.isdigit():
                return int(sem_str)
            m = re.search(r'([0-9IVXLCDM]+)', sem_str, re.IGNORECASE)
            if m:
                token = m.group(1).upper()
                if token.isdigit():
                    return int(token)
                romans = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
                res = 0
                p = 0
                valid = True
                for c in reversed(token):
                    if c not in romans:
                        valid = False
                        break
                    v = romans[c]
                    if v < p:
                        res -= v
                    else:
                        res += v
                        p = v
                if valid and res > 0:
                    return res

        raise ValueError(f"Could not determine semester for worksheet '{sheet_name}' (cell D2 value: {cell_val})")

    @staticmethod
    def _get_section(sheet_name: str) -> str:
        parts = sheet_name.split()
        if len(parts) >= 3 and not parts[-2].startswith("(S"):
            return parts[-2]
        return ""