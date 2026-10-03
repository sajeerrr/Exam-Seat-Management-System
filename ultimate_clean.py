import pathlib
p = pathlib.Path(r'd:\Projects\S3 project\Seat Manager\exam_allocator\templates\exam_allocator\import_data.html')
text = p.read_text('utf-8')

# Remove hero subtitle
text = text.replace('<p>Upload student lists, exam timetable files, and classroom data. Multiple files can be selected for each category.</p>', '')

# We will remove the 3 card-desc manually using their exact strings:
text = text.replace('<div class=\"card-desc\">Upload one or more Excel (.xlsx) or PDF files containing student roll numbers, names, and class assignments.</div>', '')
text = text.replace('<div class=\"card-desc\">Upload one or more timetable files. Multiple files will be merged — useful when departments have separate timetables.</div>', '')
text = text.replace('<div class=\"card-desc\">Upload an Excel file listing each exam room with its number, building, bench count, and seating capacity.</div>', '')

# Remove drop-sublabels
text = text.replace('<div class=\"drop-sublabel\">Accepts .xlsx, .xls, .pdf • Multiple files OK</div>', '')
text = text.replace('<div class=\"drop-sublabel\">Accepts .xlsx, .xls only</div>', '')

# Remove TIPS block
t1 = text.find('<!-- TIPS -->')
t2 = text.find('{% if uploaded_files %}')
if t1 != -1 and t2 != -1:
    text = text[:t1] + text[t2:]

p.write_text(text, 'utf-8')
print('DONE')
