
import pathlib, re
p = pathlib.Path(r'd:\Projects\S3 project\Seat Manager\exam_allocator\templates\exam_allocator\import_data.html')
text = p.read_text('utf-8')
text = re.sub(r'<p>Upload student lists.*?<\/p>', '', text, flags=re.DOTALL)
text = re.sub(r'<div class=.card-desc.>.*?<\/div>', '', text, flags=re.DOTALL)
text = re.sub(r'<div class=.drop-sublabel.>.*?<\/div>', '', text, flags=re.DOTALL)
start_tips = text.find('<!-- TIPS -->')
end_tips = text.find('{% if uploaded_files %}')
if start_tips != -1 and end_tips != -1:
    text = text[:start_tips] + text[end_tips:]
p.write_text(text, 'utf-8')

