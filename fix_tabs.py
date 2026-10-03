import pathlib

p = pathlib.Path(r'd:\Projects\S3 project\Seat Manager\exam_allocator\templates\exam_allocator\review_session.html')
text = p.read_text('utf-8')

# The current switchTab looks like this:
'''
    function switchTab(name) {
        ['dept', 'tt', 'rooms'].forEach(t => {
            document.getElementById('tab-' + t).classList.toggle('active', t === name);
            document.getElementById('panel-' + t).classList.toggle('active', t === name);
        });
    }
'''

new_switch_tab = '''
    function switchTab(name) {
        sessionStorage.setItem('reviewActiveTab', name);
        ['dept', 'tt', 'rooms'].forEach(t => {
            document.getElementById('tab-' + t).classList.toggle('active', t === name);
            document.getElementById('panel-' + t).classList.toggle('active', t === name);
        });
    }
    
    document.addEventListener('DOMContentLoaded', () => {
        const active = sessionStorage.getItem('reviewActiveTab');
        if (active) switchTab(active);
    });
'''

import re
# We handle varying spaces with a regex
text = re.sub(
    r'function switchTab\(name\) \{.*?\n\s*\}\n', 
    new_switch_tab.strip() + '\n\n', 
    text, 
    flags=re.DOTALL
)

p.write_text(text, 'utf-8')
print('Fixed switchTab logic!')
