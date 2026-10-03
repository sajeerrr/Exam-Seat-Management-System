import pathlib

p = pathlib.Path(r'd:\Projects\S3 project\Seat Manager\exam_allocator\templates\exam_allocator\review_session.html')
text = p.read_text('utf-8')

# Fix department_code tag
old_dept = 'font-size:13px;\">({{\n                        dept.department_code }})</span>'
new_dept = 'font-size:13px;\">({{ dept.department_code }})</span>'

if old_dept in text:
    text = text.replace(old_dept, new_dept)
else:
    # try a more relaxed replacement
    import re
    text = re.sub(r'\(\{\{\s*\n\s*dept\.department_code \}\}\)', '({{ dept.department_code }})', text)

# Fix pluralize tag
old_plural = 'class{{ dept.classes.count|pluralize:\"es\"\n                        }}</span>'
new_plural = 'class{{ dept.classes.count|pluralize:\"es\" }}</span>'

if old_plural in text:
    text = text.replace(old_plural, new_plural)
else:
    import re
    text = re.sub(r'class\{\{\s*dept\.classes\.count\|pluralize:\"es\"\s*\n\s*\}\}', 'class{{ dept.classes.count|pluralize:\"es\" }}', text)

p.write_text(text, 'utf-8')
print('Fixed dashboard tags')
