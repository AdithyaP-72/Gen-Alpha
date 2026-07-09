import docx
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import os

doc = docx.Document('AIML report.docx')

# 1. Remove watermark border
for sec in doc.sections:
    hdr = sec.header
    for p in hdr.paragraphs:
        for run in p.runs:
            for el in run._element:
                if el.tag.endswith('pict'):
                    for shape in el:
                        if shape.tag.endswith('shape'):
                            shape.set('stroked', 'f')

# 2. Remove all old inline images
for p in doc.paragraphs:
    for run in p.runs:
        drawing_elements = [el for el in run._element if el.tag.endswith('drawing')]
        for el in drawing_elements:
            run._element.remove(el)

def add_image_after(p, img_path, caption=""):
    if not os.path.exists(img_path):
        return p
    # Add a new paragraph after p
    new_p = p.insert_paragraph_before('')
    # move new_p after p by inserting p before new_p's next sibling?
    # Python-docx doesn't have an easy insert_after. We will insert before the next paragraph.
    next_p = p._element.getnext()
    if next_p is not None:
        new_p = docx.text.paragraph.Paragraph(next_p, p._parent).insert_paragraph_before('')
    else:
        new_p = doc.add_paragraph()
        
    new_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = new_p.add_run()
    run.add_picture(img_path, width=Inches(6.0))
    
    if caption:
        if next_p is not None:
            cap_p = docx.text.paragraph.Paragraph(next_p, p._parent).insert_paragraph_before('')
        else:
            cap_p = doc.add_paragraph()
        cap_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap_run = cap_p.add_run(f"Figure: {caption}")
        cap_run.italic = True
        return cap_p
    return new_p

# Helper to find paragraph by text prefix
def find_paragraph(prefix):
    for p in doc.paragraphs:
        if p.text.strip().startswith(prefix):
            return p
    return None

# Mapping images
# Intro / Block Diagram
p_intro = find_paragraph("System Architecture & Block Diagram")
if p_intro:
    add_image_after(p_intro, 'pics2/dashboard.png', 'Intelligent Alpha Mining Dashboard')

# Add Dataset Description and Algorithm after IV Design Methodology Tools (Specifically after WorldQuant API Simulation Engine)
p_wq = find_paragraph("WorldQuant API Simulation Engine")
if p_wq:
    # We insert our text after this paragraph
    # We will just append them to the end of the document, but since we want them inside section IV,
    # we'll insert before V. Result Analysis
    p_v = find_paragraph("V. Result Analysis")
    
    if p_v:
        # Insert Dataset Description
        p_ds_title = p_v.insert_paragraph_before('Dataset Description', style='Heading 2')
        p_ds_text = p_v.insert_paragraph_before(
            "The dataset utilized for the intelligent alpha mining pipeline is intrinsically dynamic and organically derived from the system's own iterative simulation loops. Termed 'simulation_history.json', this corpus captures the comprehensive metadata, structural features, and performance metrics of every machine-generated quantitative expression evaluated by the WorldQuant BRAIN API. Feature engineering forms the core of our dataset preparation. Raw mathematical expressions are parsed into structural proxies including 'Expression Length', 'Has TS_', 'Has Group_', 'Decay', 'Truncation', and 'Neutralization'.")
        p_ds_text.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        
        last_inserted = add_image_after(p_ds_text, 'pics2/alphas to be simulated.png', 'Alphas Evaluated by ML Predictor')
        
        # Insert Algorithm Chosen
        p_alg_title = p_v.insert_paragraph_before('6. Algorithm(s) chosen for Model Building (with a brief justification for the selection)', style='Heading 2')
        p_alg_text = p_v.insert_paragraph_before(
            "The architectural selection for the ML pre-screener was driven by the specific constraints and statistical properties of quantitative financial data. Following an exhaustive head-to-head benchmarking phase involving 16 distinct algorithmic approaches, the Gradient Boosting ensemble method emerged as the definitively superior architecture. It handles severe class imbalance natively through sequential error-correction, drastically outperforming deep neural networks on our limited dataset size (n < 500).")
        p_alg_text.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        
        # Insert images
        cap1 = add_image_after(p_alg_text, 'pics2/classifications tried.png', 'Classification Algorithms Benchmarked')
        if cap1:
            cap2 = add_image_after(cap1, 'pics2/regressions tried.png', 'Regression Algorithms Benchmarked')
            if cap2:
                cap3 = add_image_after(cap2, 'pics2/feature_importance.png', 'Gradient Boosting Feature Importance')
                if cap3:
                    add_image_after(cap3, 'pics2/confusion_matrix.png', 'Gradient Boosting Confusion Matrix')


# Result Analysis
p_results = find_paragraph("V. Result Analysis")
if p_results:
    cap_r1 = add_image_after(p_results, 'pics2/papers scanned and alphas derived pop up.png', 'ArXiv Papers Scanned and Alphas Derived')
    if cap_r1:
        cap_r2 = add_image_after(cap_r1, 'pics2/ml model results on the yet to be simulated alphas pop up.png', 'ML Predictor Results and Inference')
        if cap_r2:
            cap_r3 = add_image_after(cap_r2, 'pics2/alpha library with the simulated return and settings of each alpha.png', 'Alpha Library with Simulation Returns')
            if cap_r3:
                add_image_after(cap_r3, 'pics2/correlation matrix and 5 year yield simulation.png', 'Portfolio Correlation Matrix and 5-Year Yield Simulation')

# References
# Add ML References at the end
doc.add_paragraph("Friedman, J. H. (2001). Greedy function approximation: A gradient boosting machine. Annals of statistics, 1189-1232.")
doc.add_paragraph("Lopez de Prado, M. (2018). Advances in financial machine learning. John Wiley & Sons.")

doc.save('AIML report_final.docx')
print("Successfully reconstructed document.")
