import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# Core schema keys for verification payload mapping
ALLOWED_DOCUMENT_FIELDS = {
    "document_type",
    "document_category",
    "state",
    "document_number",
    "serial_number",
    "stamp_number",
    "stamp_value",
    "document_date",
    "execution_date",
}

ALLOWED_PROPERTY_FIELDS = {
    "survey_number",
    "sub_survey_number",
    "khata_number",
    "patta_number",
    "area",
    "boundaries",
    "village",
    "mandal",
    "district",
}

ALLOWED_STAMP_FIELDS = {
    "stamp_vendor",
    "stamp_vendor_type",
    "stamp_number",
    "stamp_value",
    "acknowledgement_number",
    "si_number",
    "cash_number",
    "sold_to",
    "sold_to_relation",
    "sold_to_residence",
    "for_whom",
    "license_number",
    "rl_number",
    "vendor_address",
    "vendor_phone",
}

KEYS_DIR = Path("verification_keys")
PRIVATE_KEY_PATH = KEYS_DIR / "private_key.pem"
PUBLIC_KEY_PATH = KEYS_DIR / "public_key.pem"


def get_field_value(data: Dict[str, Any], *key_paths: str, default: Any = None) -> Any:
    """
    Robust helper that retrieves a field value from a dictionary by checking
    multiple potential dot-separated key paths or top-level keys.
    """
    if not isinstance(data, dict):
        return default

    for path in key_paths:
        parts = path.split(".")
        current = data
        found = True
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                found = False
                break
        if found and current is not None:
            if isinstance(current, str):
                cleaned = current.strip()
                if cleaned:
                    return cleaned
            else:
                return current

    return default


def prepare_verification_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts and normalizes document facts and metadata for the canonical verification payload.
    Checks nested structures (e.g. property.*, stamp_information.*) as well as flat top-level keys.
    """
    payload = {}
    
    # 1. Base document attributes
    for field in ALLOWED_DOCUMENT_FIELDS:
        if field in ("stamp_number", "stamp_value"):
            payload[field] = get_field_value(result, field, f"stamp_information.{field}")
        else:
            payload[field] = get_field_value(result, field)

    # 2. Parties involved
    raw_parties = get_field_value(result, "parties", "parties_list", default=[])
    parties_payload = []
    if isinstance(raw_parties, str):
        try:
            raw_parties = json.loads(raw_parties)
        except Exception:
            raw_parties = []

    if isinstance(raw_parties, dict):
        flattened = []
        for role_key, party_list in raw_parties.items():
            if isinstance(party_list, list):
                for p in party_list:
                    if isinstance(p, dict) and "role" not in p:
                        p["role"] = role_key
                    flattened.append(p)
        raw_parties = flattened

    if isinstance(raw_parties, list):
        for party in raw_parties:
            if isinstance(party, dict):
                parties_payload.append({
                    "name": get_field_value(party, "name", "party_name", "full_name"),
                    "relation": get_field_value(party, "relation", "father_name", "spouse_name"),
                    "role": get_field_value(party, "role", "party_role", "type"),
                    "address": get_field_value(party, "address", "residence"),
                })
    payload["parties"] = parties_payload

    # 3. Property details
    raw_property = result.get("property", {})
    if not isinstance(raw_property, dict):
        raw_property = {}

    property_payload = {}
    for field in ALLOWED_PROPERTY_FIELDS:
        val = get_field_value(raw_property, field)
        if val is None:
            val = get_field_value(result, field, f"property_{field}")
        property_payload[field] = val
    payload["property"] = property_payload

    # 4. Stamp information details
    raw_stamp = result.get("stamp_information", {})
    if not isinstance(raw_stamp, dict):
        raw_stamp = {}

    stamp_payload = {}
    for field in ALLOWED_STAMP_FIELDS:
        val = get_field_value(raw_stamp, field)
        if val is None:
            val = get_field_value(result, field, f"stamp_{field}")
        stamp_payload[field] = val
    payload["stamp_information"] = stamp_payload

    # Keep top-level and nested stamp_number/stamp_value synchronized
    if not payload.get("stamp_number") and stamp_payload.get("stamp_number"):
        payload["stamp_number"] = stamp_payload["stamp_number"]
    elif payload.get("stamp_number") and not stamp_payload.get("stamp_number"):
        stamp_payload["stamp_number"] = payload["stamp_number"]

    if not payload.get("stamp_value") and stamp_payload.get("stamp_value"):
        payload["stamp_value"] = stamp_payload["stamp_value"]
    elif payload.get("stamp_value") and not stamp_payload.get("stamp_value"):
        stamp_payload["stamp_value"] = payload["stamp_value"]

    return payload


def canonicalize_document(payload: Dict[str, Any]) -> bytes:
    """
    Produces a deterministic JSON byte representation by sorting keys recursively.
    """
    def sort_recursively(item: Any) -> Any:
        if isinstance(item, dict):
            return {k: sort_recursively(item[k]) for k in sorted(item.keys())}
        elif isinstance(item, list):
            return [sort_recursively(x) for x in item]
        return item

    sorted_payload = sort_recursively(payload)
    return json.dumps(
        sorted_payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":")
    ).encode("utf-8")


def parse_date(date_str: Any) -> Any:
    if not date_str or not isinstance(date_str, str):
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def run_verification_checks(
    result: Dict[str, Any],
    file_hash: Optional[str] = None,
    current_verification_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Executes automated evaluation checks and returns a structured log of passes, warnings, and failures.
    """
    checks = []

    # Operating over canonical verification payload if not already present
    if "document_payload" in result:
        payload = result["document_payload"]
    elif "document_type" in result and "property" in result and isinstance(result.get("property"), dict):
        payload = result
    else:
        payload = prepare_verification_payload(result)

    # 0. Duplicate Document / Double-Registration Check
    dup_info = check_duplicate_document(
        payload=result,
        file_hash=file_hash,
        current_verification_id=current_verification_id,
    )
    if dup_info:
        dup_id = dup_info.get("matched_record_id", "")
        dup_sealed = dup_info.get("sealed_at", "Certified")
        dup_doc = dup_info.get("document_number", "")
        doc_txt = f" (Doc No. {dup_doc})" if dup_doc and dup_doc != "N/A" else ""
        checks.append({
            "check_id": "duplicate_document_check",
            "name": "Ledger Duplicate & Double-Registration Check",
            "status": "FAIL",
            "severity": "critical",
            "message": f"DUPLICATE DETECTED: This document{doc_txt} was already registered and cryptographically sealed on {dup_sealed} under Record No. {dup_id[:8].upper()}. Double registration is prohibited under registry rules.",
            "details": dup_info,
        })
    else:
        checks.append({
            "check_id": "duplicate_document_check",
            "name": "Ledger Duplicate & Double-Registration Check",
            "status": "PASS",
            "severity": "critical",
            "message": "Unique document. No prior sealed record found in the registry ledger.",
            "details": {},
        })

    # 1. Required field validation
    required_missing = []
    if not payload.get("document_type"):
        required_missing.append("document_type")
    if not payload.get("document_number"):
        required_missing.append("document_number")
    
    parties = payload.get("parties", [])
    if not isinstance(parties, list) or len(parties) == 0:
        raw_p = result.get("parties") or result.get("parties_list")
        if isinstance(raw_p, list) and len(raw_p) > 0:
            parties = raw_p
            payload["parties"] = raw_p
        elif isinstance(raw_p, str):
            try:
                parsed_p = json.loads(raw_p)
                if isinstance(parsed_p, list) and len(parsed_p) > 0:
                    parties = parsed_p
                    payload["parties"] = parsed_p
            except Exception:
                pass
    if not parties:
        required_missing.append("parties")

    prop = payload.get("property", {})
    if not isinstance(prop, dict) or not prop:
        prop = {}
        for k in ("survey_number", "area", "village", "district"):
            if result.get(k) is not None:
                prop[k] = result.get(k)
            elif result.get(f"property_{k}") is not None:
                prop[k] = result.get(f"property_{k}")
        payload["property"] = prop

    if not prop.get("survey_number"):
        required_missing.append("property.survey_number")
    if prop.get("area") is None:
        required_missing.append("property.area")
    if not prop.get("village"):
        required_missing.append("property.village")
    if not prop.get("district"):
        required_missing.append("property.district")

    if required_missing:
        checks.append({
            "check_id": "required_fields",
            "name": "Required Document Fields",
            "status": "FAIL",
            "severity": "critical",
            "message": f"Critical missing required fields: {', '.join(required_missing)}",
            "details": {"missing": required_missing}
        })
    else:
        checks.append({
            "check_id": "required_fields",
            "name": "Required Document Fields",
            "status": "PASS",
            "severity": "critical",
            "message": "All critical document fields are present.",
            "details": {}
        })

    # 2. Area validation
    area_val = prop.get("area") if isinstance(prop, dict) else None
    if area_val is not None:
        try:
            area_num = float(area_val)
            if area_num <= 0:
                checks.append({
                    "check_id": "area_validation",
                    "name": "Property Area Boundary Validation",
                    "status": "FAIL",
                    "severity": "critical",
                    "message": f"Invalid property area: {area_num}. Value must be greater than zero.",
                    "details": {"area": area_num}
                })
            else:
                checks.append({
                    "check_id": "area_validation",
                    "name": "Property Area Boundary Validation",
                    "status": "PASS",
                    "severity": "critical",
                    "message": f"Property area is valid ({area_num}).",
                    "details": {"area": area_num}
                })
        except (ValueError, TypeError):
            checks.append({
                "check_id": "area_validation",
                "name": "Property Area Boundary Validation",
                "status": "FAIL",
                "severity": "critical",
                "message": f"Failed to parse area value as number: {area_val}",
                "details": {"area_value": area_val}
            })
    else:
        checks.append({
            "check_id": "area_validation",
            "name": "Property Area Boundary Validation",
            "status": "FAIL",
            "severity": "critical",
            "message": "Area value is missing or null.",
            "details": {}
        })

    # 3. Date validation
    doc_date_str = result.get("document_date") or payload.get("document_date")
    exec_date_str = result.get("execution_date") or payload.get("execution_date")
    
    doc_date = parse_date(doc_date_str)
    exec_date = parse_date(exec_date_str)

    date_errors = []
    if doc_date_str and not doc_date:
        date_errors.append(f"Unparseable document date: {doc_date_str}")
    if exec_date_str and not exec_date:
        date_errors.append(f"Unparseable execution date: {exec_date_str}")

    if date_errors:
        checks.append({
            "check_id": "date_validation",
            "name": "Date Parse & Logic Validation",
            "status": "WARNING",
            "severity": "non-critical",
            "message": "; ".join(date_errors),
            "details": {"document_date": doc_date_str, "execution_date": exec_date_str}
        })
    elif doc_date and exec_date:
        # Document date is when stamp/deed is drafted; execution date is when parties sign (on or after document date)
        if exec_date < doc_date:
            checks.append({
                "check_id": "date_validation",
                "name": "Date Parse & Logic Validation",
                "status": "WARNING",
                "severity": "non-critical",
                "message": f"Execution date ({exec_date_str}) is prior to document date ({doc_date_str}).",
                "details": {"document_date": doc_date_str, "execution_date": exec_date_str}
            })
        else:
            checks.append({
                "check_id": "date_validation",
                "name": "Date Parse & Logic Validation",
                "status": "PASS",
                "severity": "non-critical",
                "message": "Document and execution dates are logically ordered.",
                "details": {"document_date": doc_date_str, "execution_date": exec_date_str}
            })
    else:
        checks.append({
            "check_id": "date_validation",
            "name": "Date Parse & Logic Validation",
            "status": "WARNING",
            "severity": "non-critical",
            "message": "Dates are missing or incomplete to verify logical ordering.",
            "details": {"document_date": doc_date_str, "execution_date": exec_date_str}
        })

    # 4. Survey number validation
    survey_no = prop.get("survey_number") if isinstance(prop, dict) else None
    if survey_no:
        clean_survey = str(survey_no).strip()
        if re.match(r"^[0-9a-zA-Z\-/,\s&]+$", clean_survey):
            checks.append({
                "check_id": "survey_number_validation",
                "name": "Survey Number Validation",
                "status": "PASS",
                "severity": "critical",
                "message": f"Survey number '{clean_survey}' format is valid.",
                "details": {"survey_number": clean_survey}
            })
        else:
            checks.append({
                "check_id": "survey_number_validation",
                "name": "Survey Number Validation",
                "status": "WARNING",
                "severity": "non-critical",
                "message": f"Survey number '{clean_survey}' contains unusual characters.",
                "details": {"survey_number": clean_survey}
            })
    else:
        checks.append({
            "check_id": "survey_number_validation",
            "name": "Survey Number Validation",
            "status": "FAIL",
            "severity": "critical",
            "message": "Survey number is missing or empty.",
            "details": {}
        })

    # 5. Geographic consistency
    # Because there's no authority connection, we warn that verification database lookup is not available
    checks.append({
        "check_id": "geographic_consistency",
        "name": "Geographic Authority Consistency",
        "status": "WARNING",
        "severity": "non-critical",
        "message": "National geographical master registry is not available in local prototype.",
        "details": {"status": "NOT_VERIFIABLE_LOCALLY"}
    })

    # 6. Extraction Quality / Signature Flags
    features = result.get("document_features", {})
    if isinstance(features, dict) and not features.get("signature_detected", True):
        checks.append({
            "check_id": "signature_detection",
            "name": "Signature Detection Check",
            "status": "WARNING",
            "severity": "non-critical",
            "message": "No visual signature blocks were detected on the page template.",
            "details": {}
        })
    else:
        checks.append({
            "check_id": "signature_detection",
            "name": "Signature Detection Check",
            "status": "PASS",
            "severity": "non-critical",
            "message": "Signature detection validated successfully.",
            "details": {}
        })

    # 7. Internal Consistency Checks
    stamp_info = result.get("stamp_information", {})
    inconsistencies = []
    if isinstance(stamp_info, dict) and isinstance(prop, dict):
        sold_to = stamp_info.get("sold_to")
        # Simple string matching helper
        if sold_to and parties:
            sold_to_clean = re.sub(r"\s+", "", str(sold_to).upper())
            party_names = [re.sub(r"\s+", "", str(p.get("name", "")).upper()) for p in parties if isinstance(p, dict)]
            if not any(sold_to_clean in p_name or p_name in sold_to_clean for p_name in party_names):
                inconsistencies.append(f"Stamp sold_to '{sold_to}' does not match any transaction party.")

    if inconsistencies:
        checks.append({
            "check_id": "internal_consistency",
            "name": "Internal Data Consistency",
            "status": "WARNING",
            "severity": "non-critical",
            "message": "; ".join(inconsistencies),
            "details": {"inconsistencies": inconsistencies}
        })
    else:
        checks.append({
            "check_id": "internal_consistency",
            "name": "Internal Data Consistency",
            "status": "PASS",
            "severity": "non-critical",
            "message": "No internal document contradictions detected.",
            "details": {}
        })

    return checks


def calculate_overall_status(checks: List[Dict[str, Any]]) -> str:
    """
    Applies aggregation rules:
    - If duplicate check is FAIL -> DUPLICATE
    - If any check is FAIL -> FAIL
    - If no FAIL but any check is WARNING -> NEEDS_REVIEW
    - If all checks are PASS -> READY_FOR_APPROVAL
    """
    is_duplicate = any(
        check.get("check_id") == "duplicate_document_check" and check.get("status") == "FAIL"
        for check in checks
    )
    if is_duplicate:
        return "DUPLICATE"

    has_fail = any(check.get("status") == "FAIL" for check in checks)
    has_warning = any(check.get("status") == "WARNING" for check in checks)
    
    if has_fail:
        return "FAIL"
    elif has_warning:
        return "NEEDS_REVIEW"
    return "READY_FOR_APPROVAL"


def create_verification_record(result: Dict[str, Any], file_hash: Optional[str] = None) -> Dict[str, Any]:
    """
    Assembles the structured in-memory verification registry item.
    """
    payload = prepare_verification_payload(result)
    checks = run_verification_checks(result, file_hash=file_hash)
    status = calculate_overall_status(checks)
    dup_info = check_duplicate_document(payload, file_hash=file_hash)
    
    return {
        "verification_id": str(uuid.uuid4()),
        "status": status,
        "file_hash": file_hash,
        "document_payload": payload,
        "checks": checks,
        "duplicate_info": dup_info,
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "decision": None,
        "signature": None,
        "public_key": None,
        "qr_code": None
    }


# =====================================================================
# Local RSA Cryptographic Sealing Layer
# =====================================================================

def get_or_create_signing_key() -> rsa.RSAPrivateKey:
    """
    Retrieves the persisted RSA private key from verification_keys/private_key.pem,
    or generates and saves a new 2048-bit key if it does not exist.
    """
    if not KEYS_DIR.exists():
        KEYS_DIR.mkdir(parents=True, exist_ok=True)

    if PRIVATE_KEY_PATH.exists():
        try:
            with open(PRIVATE_KEY_PATH, "rb") as key_file:
                return serialization.load_pem_private_key(
                    key_file.read(),
                    password=None
                )
        except Exception as e:
            raise RuntimeError(f"Failed to load existing private key: {e}")

    # Generate new RSA 2048-bit key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    
    # Save Private Key
    try:
        pem_private = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        )
        # Attempt to restrict permissions on Unix where supported
        if hasattr(os, "O_WRONLY") and hasattr(os, "O_CREAT"):
            fd = os.open(PRIVATE_KEY_PATH, os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(pem_private)
        else:
            with open(PRIVATE_KEY_PATH, "wb") as f:
                f.write(pem_private)
    except Exception as e:
        raise RuntimeError(f"Failed to save generated private key: {e}")

    # Derive and save Public Key
    public_key = private_key.public_key()
    try:
        pem_public = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with open(PUBLIC_KEY_PATH, "wb") as f:
            f.write(pem_public)
    except Exception as e:
        raise RuntimeError(f"Failed to save derived public key: {e}")

    return private_key


def get_public_verification_key() -> str:
    """
    Returns the PEM serialized public verification key as a Base64-safe string representation.
    """
    # Force creation/load of the pair to ensure key files are aligned
    get_or_create_signing_key()
    
    try:
        with open(PUBLIC_KEY_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        raise RuntimeError(f"Failed to read public key file: {e}")


def sign_document(payload: Dict[str, Any]) -> str:
    """
    Calculates RSA-PSS / SHA-256 signature over the canonical representation
    of the verification payload. Returns Base64 string signature.
    """
    private_key = get_or_create_signing_key()
    canonical_bytes = canonicalize_document(payload)

    signature = private_key.sign(
        canonical_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode("ascii")


def verify_document_signature(payload: Dict[str, Any], signature_b64: str, public_key_pem: str) -> bool:
    """
    Verifies the signature block against the reconstructed canonical representation.
    """
    try:
        # Load public key from PEM string
        pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        
        # Decode signature
        signature = base64.b64decode(signature_b64.encode("ascii"))
        
        # Canonicalize document
        canonical_bytes = canonicalize_document(payload)
        
        # Verify using RSA-PSS
        pub_key.verify(
            signature,
            canonical_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return True
    except (InvalidSignature, ValueError, TypeError, Exception):
        return False


# =====================================================================
# Database Persistence Layer (verification_db.json)
# =====================================================================

DB_PATH = Path("verification_db.json")


def load_db() -> Dict[str, Any]:
    """Reads the local JSON database file."""
    if not DB_PATH.exists():
        return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_db(db: Dict[str, Any]) -> None:
    """Writes the database structure to the local JSON file."""
    try:
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise RuntimeError(f"Failed to write verification database: {e}")


def get_record(verification_id: str) -> Dict[str, Any]:
    """Retrieves a single verification record by ID."""
    db = load_db()
    return db.get(verification_id)


def save_record(record: Dict[str, Any]) -> None:
    """
    Saves or updates a verification record, enforcing strict immutability
    once the document state reaches APPROVED.
    """
    verification_id = record.get("verification_id")
    if not verification_id:
        raise ValueError("Record is missing a verification_id")

    db = load_db()
    existing = db.get(verification_id)

    if existing and existing.get("status") == "APPROVED":
        # Check if the document payload or key verification elements are being tampered with
        if existing.get("document_payload") != record.get("document_payload"):
            raise ValueError("Immutable approved records cannot be modified.")

    db[verification_id] = record
    save_db(db)


def check_duplicate_document(
    payload: Optional[Dict[str, Any]] = None,
    file_hash: Optional[str] = None,
    current_verification_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Checks the local verification database for an already APPROVED/sealed document
    matching this file hash or canonical document identity.
    """
    db = load_db()
    if not db:
        return None

    target_hash = (file_hash or "").strip().lower() if file_hash else None
    
    target_doc_no = None
    target_stamp_no = None
    target_village = None
    target_district = None
    target_survey = None
    
    if isinstance(payload, dict):
        doc_data = payload.get("document_payload") if "document_payload" in payload else payload
        target_doc_no = get_field_value(doc_data, "document_number", "document_no")
        target_stamp_no = get_field_value(doc_data, "stamp_number", "serial_number", "stamp_serial_number", "stamp_information.stamp_number")
        target_village = get_field_value(doc_data, "property.village", "village", "property_village")
        target_district = get_field_value(doc_data, "property.district", "district", "property_district")
        target_survey = get_field_value(doc_data, "property.survey_number", "survey_number", "property_survey_number")

    def _normalize_id(s: Any) -> str:
        if not s:
            return ""
        return re.sub(r"[^a-zA-Z0-9]", "", str(s)).lower()

    norm_target_doc = _normalize_id(target_doc_no)
    norm_target_stamp = _normalize_id(target_stamp_no)
    norm_target_village = _normalize_id(target_village)
    norm_target_survey = _normalize_id(target_survey)

    ignored = {"", "none", "null", "unknown", "na", "notfound", "nil", "unnumbered"}
    if norm_target_doc in ignored or len(norm_target_doc) < 3:
        norm_target_doc = ""
    if norm_target_stamp in ignored or len(norm_target_stamp) < 4:
        norm_target_stamp = ""

    for vid, rec in db.items():
        if not isinstance(rec, dict):
            continue
        if current_verification_id and vid == current_verification_id:
            continue
        # Only check against officially APPROVED / sealed records
        if rec.get("status") != "APPROVED":
            continue

        existing_hash = (rec.get("file_hash") or "").strip().lower()
        existing_payload = rec.get("document_payload") or {}
        existing_doc_no = get_field_value(existing_payload, "document_number", "document_no")
        existing_stamp_no = get_field_value(existing_payload, "stamp_number", "serial_number", "stamp_information.stamp_number")
        existing_village = get_field_value(existing_payload, "property.village", "village")
        existing_district = get_field_value(existing_payload, "property.district", "district")
        existing_survey = get_field_value(existing_payload, "property.survey_number", "survey_number")

        norm_exist_doc = _normalize_id(existing_doc_no)
        norm_exist_stamp = _normalize_id(existing_stamp_no)
        norm_exist_village = _normalize_id(existing_village)
        norm_exist_survey = _normalize_id(existing_survey)

        matched = False
        match_reason = ""

        # 1. Identical cryptographic file hash
        if target_hash and existing_hash and target_hash == existing_hash:
            matched = True
            match_reason = "Identical cryptographic file hash (exact same document scan uploaded)"
        
        # 2. Matching Registered Document Number
        elif norm_target_doc and norm_exist_doc and norm_target_doc == norm_exist_doc:
            if (norm_target_village and norm_exist_village and norm_target_village == norm_exist_village) or \
               (norm_target_survey and norm_exist_survey and norm_target_survey == norm_exist_survey) or \
               len(norm_target_doc) >= 4:
                matched = True
                match_reason = f"Matching registered Document Number ({existing_doc_no})"

        # 3. Matching Stamp Serial Number + Village or Survey
        elif norm_target_stamp and norm_exist_stamp and norm_target_stamp == norm_exist_stamp:
            if (norm_target_village and norm_exist_village and norm_target_village == norm_exist_village) or \
               (norm_target_survey and norm_exist_survey and norm_target_survey == norm_exist_survey) or \
               len(norm_target_stamp) >= 6:
                matched = True
                match_reason = f"Matching Stamp Serial Number ({existing_stamp_no})"

        if matched:
            return {
                "is_duplicate": True,
                "matched_record_id": vid,
                "matched_status": rec.get("status"),
                "sealed_at": rec.get("approved_at") or rec.get("created_at") or "Certified",
                "document_number": existing_doc_no or target_doc_no or "N/A",
                "survey_number": existing_survey or target_survey or "N/A",
                "village": existing_village or target_village or "N/A",
                "match_reason": match_reason,
            }

    return None

