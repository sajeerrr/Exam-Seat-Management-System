import pymupdf
doc = pymupdf.open("/home/petercj/Documents/Dev/Mini_project/resources/inputs/timetable4.pdf")
page = doc[0]
for i, table in enumerate(page.find_tables().tables):
    print(f"--- table {i}: {table.row_count} rows x {table.col_count} cols ---")
    for row in table.extract():
        print(row)