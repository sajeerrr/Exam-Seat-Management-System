# ExamSeat

**High-Performance Academic Seating Allocation & Blueprint Management System**

ExamSeat transforms student registries, exam timetables, and classroom floor plans into clash-free, optimized seating arrangements. Powered by Google OR-Tools constraint solving and Django, it eliminates spreadsheet chaos and enforces strict department interleaving across examination halls.

---

## Key Capabilities

- **Intelligent Branch Interleaving**: Employs constraint programming to ensure students from the same department or subject are never seated adjacently.
- **Multi-Format Ingestion**: Ingests student enrollment lists, timetable schedules (FN / AN sessions), and hall capacities directly from Excel (`.xlsx`, `.xls`), CSV, and PDF documents.
- **Interactive Blueprint Review**: Visualizes seating plans room-by-room with detailed bench grids, roll sequence tracking, and hall occupancy indicators.
- **Conflict & Integrity Verification**: Automatically checks for hall capacity limits, unallocated student warnings, and timetable overlaps before finalizing plans.
- **Export & Dispatch**: Generates print-ready PDF seating charts, classroom door notices, and invigilation attendance slips with one click.

---

## Tech Stack

| Component | Technology |
| :--- | :--- |
| **Backend & Web Framework** | Python 3.11+, Django 5.x |
| **Constraint Solver** | Google OR-Tools |
| **Data Ingestion & Processing** | Pandas, OpenPyXL |
| **Document Processing & PDF** | PyMuPDF (`pymupdf`) |
| **Database** | SQLite (development) / PostgreSQL (production) |
| **Interface** | Responsive Monochrome Design System (iOS / macOS Minimalist) |

---

## Quickstart

### 1. Set Up Virtual Environment

```bash
# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate   # Windows
# source venv/bin/activate # Linux / macOS
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Database Migrations

```bash
python manage.py migrate
```

### 4. Start Development Server

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in your browser.

---

## Core Workflow

```
1. Create Session ──► 2. Upload Data (Students, Timetable, Halls) ──► 3. Generate Allocation ──► 4. Review Blueprint ──► 5. Export PDFs
```

1. **Session Setup**: Initialize an exam cycle (e.g., *Autumn Semester 2026*).
2. **Data Import**: Upload student rosters, slot schedules, and classroom capacity matrices.
3. **Engine Execution**: The constraint solver balances room densities and interleaves departments.
4. **Blueprint Review**: Inspect the interactive hall grids to verify seat placement and department separation.
5. **PDF Export**: Download final seating plans and room slips for campus distribution.

---

## Running Tests

Execute the automated test suite:

```bash
python manage.py test
```

---

## License

Proprietary / Academic Use. All rights reserved.
