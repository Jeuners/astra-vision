from astra.documents import extract_pdf_text

# Minimal hand-built single-page PDF with a text-showing operator. pypdf
# recovers it via its xref-scanning fallback despite the bogus startxref
# offset, so no external PDF-writing dependency is needed for the fixture.
MINIMAL_PDF = b"""%PDF-1.1
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/MediaBox[0 0 200 200]/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 44>>stream
BT /F1 24 Tf 20 100 Td (Hallo Astra) Tj ET
endstream
endobj
trailer<</Size 6/Root 1 0 R>>
startxref
0
%%EOF"""


def test_extract_pdf_text_reads_page_content():
    assert extract_pdf_text(MINIMAL_PDF) == "Hallo Astra"


def test_extract_pdf_text_respects_max_chars():
    text = extract_pdf_text(MINIMAL_PDF, max_chars=5)
    assert text == "Hallo"
