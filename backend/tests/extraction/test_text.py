from app.extraction.registry import extract_document
from app.extraction.sniff import MIME_TEXT


def test_extract_text_document() -> None:
    content = "Contract between Party A and Party B.\nTermination clause: 30 days.\n"
    data = content.encode("utf-8")
    extracted = extract_document(data)
    assert extracted.mime_sniffed == MIME_TEXT
    assert extracted.text == content
    assert len(extracted.pages) == 1
    assert extracted.pages[0].page_no == 1
    assert extracted.pages[0].text == content
    assert extracted.char_count == len(content)
    assert not extracted.ocr_used
