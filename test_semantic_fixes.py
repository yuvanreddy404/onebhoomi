"""
Validation test for semantic extraction fixes using the exact raw OCR lines
from the user's latest test run.
"""

from land_document_extractor import OCRLine
from semantic_extractor import extract_fields_semantic


def create_exact_ocr_lines():
    lines = [
        # PAGE 1
        OCRLine(text="no12736/5 100Rs.", score=0.92, x_min=100, y_min=50, x_max=400, y_max=90, page_num=1, page_height=2000),
        OCRLine(text="Purchased By : P.SRINIVAS REDDY", score=0.95, x_min=100, y_min=120, x_max=500, y_max=160, page_num=1, page_height=2000),
        OCRLine(text="Serial No. 11,676 D09-10-2003", score=0.95, x_min=100, y_min=180, x_max=600, y_max=220, page_num=1, page_height=2000),
        OCRLine(text="E_A__L__E___D__E__E__D", score=0.90, x_min=250, y_min=300, x_max=600, y_max=340, page_num=1, page_height=2000),
        OCRLine(text="THIS DEED OF SALE is made and executed on this the 15th day of October 2003 by", score=0.97, x_min=100, y_min=380, x_max=900, y_max=420, page_num=1, page_height=2000),
        OCRLine(text="M/s. SRINIDHI HOMES PRIVATE LIMITED, represented by its Director Sri P. SRINIVAS REDDY", score=0.96, x_min=100, y_min=440, x_max=900, y_max=480, page_num=1, page_height=2000),
        OCRLine(text="SMT. B. SUVARNA W/O SRI. B. YADAIAH", score=0.96, x_min=100, y_min=520, x_max=600, y_max=560, page_num=1, page_height=2000),
        OCRLine(text="HEREINAFTER CALLED THE PURCHASER", score=0.98, x_min=100, y_min=580, x_max=500, y_max=620, page_num=1, page_height=2000),

        # PAGE 2
        OCRLine(text="Aushapur Village, Ghatkosar Mandal, Ranga Reddy District", score=0.96, x_min=100, y_min=300, x_max=700, y_max=340, page_num=2, page_height=2000),
        OCRLine(text="WHEREAS the VENDOR has offered to sell a piece of land ad-measuring 480 Sq. yds., or 401.4 Sq. Mtrs.", score=0.95, x_min=100, y_min=400, x_max=850, y_max=440, page_num=2, page_height=2000),
        OCRLine(text="Marked as plot No. 1023/1 & 1023/2 in Survey Nos. 278, 281 situated at Aushapur", score=0.94, x_min=100, y_min=460, x_max=800, y_max=500, page_num=2, page_height=2000),

        # PAGE 5
        OCRLine(text="SCHEDULE OF PROPERTY", score=0.99, x_min=300, y_min=200, x_max=600, y_max=240, page_num=5, page_height=2000),
        OCRLine(text="Plot Nos. 1023/1 & 1023/2 in Survey Nos. 278, 281 & 282", score=0.96, x_min=100, y_min=300, x_max=700, y_max=340, page_num=5, page_height=2000),

        # PAGE 6
        OCRLine(text="PLOT AREA: 480.0 SQ YDS.", score=0.98, x_min=100, y_min=250, x_max=500, y_max=290, page_num=6, page_height=2000),
        OCRLine(text="401.4 SQ. MTS.", score=0.98, x_min=100, y_min=300, x_max=400, y_max=340, page_num=6, page_height=2000),
        OCRLine(text="Survey Nos. 282, Plot Nos. 1023/1 & 1023/2", score=0.95, x_min=100, y_min=360, x_max=650, y_max=400, page_num=6, page_height=2000),
    ]
    return lines


def test_reference_extraction():
    lines = create_exact_ocr_lines()
    result, provenance, debug_table = extract_fields_semantic(lines)

    print("==================================================")
    print("EXTRACTED STRUCTURED JSON")
    print("==================================================")
    import json
    print(json.dumps(result, indent=2))

    print("\n==================================================")
    print("VERIFYING ALL 14 FIELDS")
    print("==================================================")

    # 1. document_type
    assert result["document_type"] == "Sale Deed", f"FAIL document_type: {result['document_type']}"
    print("[PASS] document_type:       ", result["document_type"])

    # 2. document_number
    assert result["document_number"] == "12736/2003", f"FAIL document_number: {result['document_number']}"
    print("[PASS] document_number:     ", result["document_number"])

    # 3. survey_number
    assert result["survey_number"] == "278, 281, 282", f"FAIL survey_number: {result['survey_number']}"
    print("[PASS] survey_number:       ", result["survey_number"])

    # 4. sub_survey_number
    assert result["sub_survey_number"] in ("1023/1, 1023/2", "1023/1 & 1023/2"), f"FAIL sub_survey_number: {result['sub_survey_number']}"
    print("[PASS] sub_survey_number:   ", result["sub_survey_number"])

    # 5. property_area
    assert result["property_area"] == 480, f"FAIL property_area: {result['property_area']}"
    print("[PASS] property_area:       ", result["property_area"])

    # 6. village
    assert result["village"] == "Aushapur", f"FAIL village: {result['village']}"
    print("[PASS] village:             ", result["village"])

    # 7. mandal
    assert result["mandal"] == "Ghatkesar", f"FAIL mandal: {result['mandal']}"
    print("[PASS] mandal:              ", result["mandal"])

    # 8. district
    assert result["district"] == "R.R. District (Ranga Reddy District)", f"FAIL district: {result['district']}"
    print("[PASS] district:            ", result["district"])

    # 9. stamp_serial_number
    assert result["stamp_serial_number"] == "11,676", f"FAIL stamp_serial_number: {result['stamp_serial_number']}"
    print("[PASS] stamp_serial_number: ", result["stamp_serial_number"])

    # 10. stamp_value
    assert result["stamp_value"] == "Rs. 100", f"FAIL stamp_value: {result['stamp_value']}"
    print("[PASS] stamp_value:         ", result["stamp_value"])

    # 11. stamp_sold_to
    assert result["stamp_sold_to"] == "P. Srinivas Reddy", f"FAIL stamp_sold_to: {result['stamp_sold_to']}"
    print("[PASS] stamp_sold_to:       ", result["stamp_sold_to"])

    # 12. parties_list
    assert len(result["parties_list"]) == 2, f"FAIL parties_list count: {len(result['parties_list'])}"
    vendor = result["parties_list"][0]
    purchaser = result["parties_list"][1]

    assert "Srinidhi Homes" in vendor["name"], f"FAIL vendor name: {vendor['name']}"
    assert vendor["role"] == "Vendor"
    assert "Srinivas Reddy" in vendor.get("represented_by", "")

    assert purchaser["name"] == "Smt. B. Suvarna", f"FAIL purchaser name: {purchaser['name']}"
    assert purchaser["role"] == "Purchaser"
    assert "Yadaiah" not in purchaser["name"], "Yadaiah must NOT be purchaser name!"
    print("[PASS] parties_list (Vendor):   ", vendor)
    print("[PASS] parties_list (Purchaser):", purchaser)

    # 13. document_date
    assert result["document_date"] == "09-10-2003", f"FAIL document_date: {result['document_date']}"
    print("[PASS] document_date:       ", result["document_date"])

    # 14. execution_date
    assert result["execution_date"] == "15-10-2003", f"FAIL execution_date: {result['execution_date']}"
    print("[PASS] execution_date:      ", result["execution_date"])

    print("\nALL 14 FIELDS VALIDATED 100% CORRECTLY!")


if __name__ == "__main__":
    test_reference_extraction()
