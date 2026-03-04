import os
from pdf2image import convert_from_bytes
from fpdf import FPDF

# This is where we handle the Poppler path portably
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POPPLER_PATH = os.path.join(BASE_DIR, "poppler-25.12.0", "Library", "bin")


def process_pdf_to_images(pdf_bytes):
    """Converts PDF bytes to a list of PIL images."""
    try:
        if os.path.exists(POPPLER_PATH):
            images = convert_from_bytes(
                pdf_bytes,
                poppler_path=POPPLER_PATH
            )
        else:
            # Fallback (for Linux / deployment)
            images = convert_from_bytes(pdf_bytes)

        processed_images = []
        for img in images[:3]: # Reduce to 3 pages for better stability
            # Resize to a max width/height to save tokens
            img.thumbnail((1200, 1200)) 
            processed_images.append(img)
            
        return processed_images

    except Exception as e:
        raise Exception(f"Poppler Error: {e}")

def generate_study_pdf(data):
    pdf = FPDF()
    
    # 1. Path to your new fonts folder
    fonts_dir = os.path.join(BASE_DIR, "fonts")
    
    # 2. Register the fonts
    # Note: Ensure these filenames match EXACTLY what you moved
    regular_font = os.path.join(fonts_dir, "web fonts", "dejavusans_regular_macroman", "DejaVuSans-webfont.ttf")
    bold_font = os.path.join(fonts_dir, "web fonts", "dejavusans_bold_macroman", "DejaVuSans-Bold-webfont.ttf")

    if os.path.exists(regular_font) and os.path.exists(bold_font):
        pdf.add_font("DejaVu", "", regular_font)
        pdf.add_font("DejaVu", "B", bold_font)
        font_name = "DejaVu"
    else:
        # Emergency fallback if you forgot to move the files!
        print(f"⚠️ Font files not found at {fonts_dir}. Falling back to Arial.")
        font_name = "Arial"

    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # 3. Use the new font!
    pdf.set_font(font_name, 'B', 16)
    pdf.cell(0, 10, "AI Study Buddy: Summary & Notes", ln=True, align='C')
    pdf.ln(10)
    
    # Summary Section
    pdf.set_font(font_name, 'B', 12)
    pdf.cell(0, 10, "Summary:", ln=True)
    pdf.set_font(font_name, '', 11)
    pdf.multi_cell(0, 10, data['summary'])
    pdf.ln(5)
    
    # Key Terms Section
    pdf.set_font(font_name, 'B', 12)
    pdf.cell(0, 10, "Key Terms:", ln=True)
    for item in data['key_terms']:
        pdf.set_font(font_name, 'B', 10)
        pdf.cell(0, 8, f"- {item['term']}:", ln=True)
        pdf.set_font(font_name, '', 10)
        pdf.multi_cell(0, 8, item['definition'])
        pdf.ln(2)
        
    return bytes(pdf.output())