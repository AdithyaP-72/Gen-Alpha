import docx
from lxml import etree
doc = docx.Document('AIML report.docx')
for sec in doc.sections:
    hdr = sec.header
    for p in hdr.paragraphs:
        for run in p.runs:
            for el in run._element:
                if el.tag.endswith('pict'):
                    for shape in el:
                        if shape.tag.endswith('shape'):
                            shape.set('stroked', 'f')
doc.save('test_watermark.docx')
