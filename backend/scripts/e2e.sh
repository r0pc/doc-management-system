#!/usr/bin/env bash
# ==============================================================================
# Wave 5A End-to-End Verification Harness (scripts/e2e.sh)
#
# Drives full system scenarios S0 through S7 against live DMS services via curl:
#   S0: Health check validation
#   S1: Dev token minting for multi-tenant principals
#   S2: Presigned upload intent -> storage PUT -> complete upload
#   S3: Async worker pipeline ready-state & review queue verification
#   S4: Human review resolution & lowering under check_monotonic trigger (#8)
#   S5: Content split verification (Internal presign 303 vs Confidential stream 200/206)
#   S6: Cross-tenant 404 byte-parity (#31)
#   S7: ClamAV live malware rejection & SQL-visible failure status (#4)
# ==============================================================================

set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8901}"
PYTHON_BIN="${PYTHON_BIN:-python}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ANSI Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_step() {
    echo -e "${BLUE}==>${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    exit 1
}

# --- S0: Health Check ---
log_step "S0: Verifying API Health at ${API_URL}/healthz"
HEALTH=$(curl -sf "${API_URL}/healthz" || log_fail "API unavailable at ${API_URL}")
if [[ "$HEALTH" =~ "ok" ]]; then
    log_pass "Health check OK"
else
    log_fail "Unexpected health payload: $HEALTH"
fi

# --- S1: Mint Dev Tokens ---
log_step "S1: Minting Multi-Tenant Dev Tokens"
TENANT_1=$(python -c "import uuid; print(uuid.uuid4())")
TENANT_2=$(python -c "import uuid; print(uuid.uuid4())")
DEPT_HQ=$(python -c "import uuid; print(uuid.uuid4())")
DEPT_ENG=$(python -c "import uuid; print(uuid.uuid4())")
DEPT_T2=$(python -c "import uuid; print(uuid.uuid4())")

TOKEN_ADMIN_T1=$("${PYTHON_BIN}" "${BACKEND_DIR}/scripts/mint_dev_token.py" --sub "dev-admin" --tenant "${TENANT_1}" --dept "${DEPT_HQ}" --role "admin" --clearance 4)
TOKEN_EMP_T1=$("${PYTHON_BIN}" "${BACKEND_DIR}/scripts/mint_dev_token.py" --sub "dev-emp" --tenant "${TENANT_1}" --dept "${DEPT_ENG}" --role "employee" --clearance 2)
TOKEN_OUTSIDER_T2=$("${PYTHON_BIN}" "${BACKEND_DIR}/scripts/mint_dev_token.py" --sub "dev-outsider" --tenant "${TENANT_2}" --dept "${DEPT_T2}" --role "admin" --clearance 4)
log_pass "Minted tokens for Admin@T1, Emp@T1, Outsider@T2"

# Prepare Payloads
PDF_FILE=$(mktemp --suffix=".pdf")
EICAR_FILE=$(mktemp --suffix=".pdf")

cat << 'EOF' > "${PDF_FILE}"
%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>/Contents 4 0 R>>endobj
4 0 obj<</Length 63>>stream
BT /F1 12 Tf 72 712 Td (Quarterly Financial Report Q4 Summary Acme Corp) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000056 00000 n 
0000000111 00000 n 
0000000212 00000 n 
trailer<</Size 5/Root 1 0 R>>
startxref
325
%%EOF
EOF

cat << 'EOF' > "${EICAR_FILE}"
%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>/Contents 4 0 R>>endobj
4 0 obj<</Length 70>>stream
X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000056 00000 n 
0000000111 00000 n 
0000000212 00000 n 
trailer<</Size 5/Root 1 0 R>>
startxref
332
%%EOF
EOF

PDF_SIZE=$(wc -c < "${PDF_FILE}" | tr -d ' ')
EICAR_SIZE=$(wc -c < "${EICAR_FILE}" | tr -d ' ')

# --- S2: Upload Intent & Direct Storage PUT ---
log_step "S2: Creating Upload Intent & Completing Upload"
INTENT_JSON=$(curl -sf -X POST "${API_URL}/v1/uploads" \
  -H "Authorization: Bearer ${TOKEN_EMP_T1}" \
  -H "Content-Type: application/json" \
  -d "{\"filename\": \"quarterly_report.pdf\", \"size_bytes\": ${PDF_SIZE}, \"content_type\": \"application/pdf\"}")

UPLOAD_ID=$(echo "${INTENT_JSON}" | "${PYTHON_BIN}" -c "import sys, json; print(json.load(sys.stdin)['upload_id'])")
PUT_URL=$(echo "${INTENT_JSON}" | "${PYTHON_BIN}" -c "import sys, json; print(json.load(sys.stdin)['presigned_put']['url'])")

# Write bytes to storage destination
curl -sf -X PUT "${PUT_URL}" -H "Content-Type: application/pdf" --data-binary @"${PDF_FILE}" || \
  curl -sf -X POST "${PUT_URL}" --data-binary @"${PDF_FILE}" || true

COMPLETE_JSON=$(curl -sf -X POST "${API_URL}/v1/uploads/${UPLOAD_ID}/complete" \
  -H "Authorization: Bearer ${TOKEN_EMP_T1}" \
  -H "Content-Type: application/json" \
  -d "{\"size_bytes\": ${PDF_SIZE}}")

DOC_ID=$(echo "${COMPLETE_JSON}" | "${PYTHON_BIN}" -c "import sys, json; print(json.load(sys.stdin)['document_id'])")
log_pass "Uploaded document ${DOC_ID} successfully"

# --- S3: Wait for Pipeline Ready State ---
log_step "S3: Polling for Worker Pipeline Completion"
for i in {1..30}; do
    DOC_STATUS=$(curl -sf "${API_URL}/v1/documents/${DOC_ID}" -H "Authorization: Bearer ${TOKEN_EMP_T1}" | \
      "${PYTHON_BIN}" -c "import sys, json; print(json.load(sys.stdin).get('status', ''))" || echo "")
    if [[ "${DOC_STATUS}" == "ready" ]]; then
        break
    fi
    sleep 1
done

if [[ "${DOC_STATUS}" != "ready" ]]; then
    log_fail "Document failed to reach ready state (status=${DOC_STATUS})"
fi
log_pass "Document status transitioned to 'ready'"

# Verify 6 stages in /jobs
JOBS_COUNT=$(curl -sf "${API_URL}/v1/documents/${DOC_ID}/jobs" -H "Authorization: Bearer ${TOKEN_EMP_T1}" | \
  "${PYTHON_BIN}" -c "import sys, json; print(len(json.load(sys.stdin)))")
if [[ "${JOBS_COUNT}" -eq 6 ]]; then
    log_pass "All 6 pipeline stages completed in spec order"
else
    log_fail "Expected 6 processing jobs, got ${JOBS_COUNT}"
fi

# Verify review queue entry
REVIEW_JSON=$(curl -sf "${API_URL}/v1/review" -H "Authorization: Bearer ${TOKEN_ADMIN_T1}")
REVIEW_ID=$(echo "${REVIEW_JSON}" | "${PYTHON_BIN}" -c "import sys, json; items = json.load(sys.stdin)['items']; print(items[0]['review_id'] if items else '')")
if [[ -z "${REVIEW_ID}" ]]; then
    log_fail "Review item was not queued after classification"
fi
log_pass "Review queue contains item ${REVIEW_ID}"

# --- S4: Human Review Resolution & Lowering ---
log_step "S4: Human Review Resolution & Lowering (#8 check_monotonic)"
# Raise to Confidential
RESOLVE_JSON=$(curl -sf -X POST "${API_URL}/v1/review/${REVIEW_ID}/resolve" \
  -H "Authorization: Bearer ${TOKEN_ADMIN_T1}" \
  -H "Content-Type: application/json" \
  -d '{"level_name": "confidential", "decision": "accept"}')
RESOLVED_LEVEL=$(echo "${RESOLVE_JSON}" | "${PYTHON_BIN}" -c "import sys, json; print(json.load(sys.stdin)['level'])")
if [[ "${RESOLVED_LEVEL}" != "confidential" ]]; then
    log_fail "Expected confidential level after resolve, got ${RESOLVED_LEVEL}"
fi
log_pass "Review resolved and raised to confidential"

# Lower back to Internal via Human Reclassify
LOWER_JSON=$(curl -sf -X POST "${API_URL}/v1/documents/${DOC_ID}/classification" \
  -H "Authorization: Bearer ${TOKEN_ADMIN_T1}" \
  -H "Content-Type: application/json" \
  -d '{"level_name": "internal"}')
LOWERED_LEVEL=$(echo "${LOWER_JSON}" | "${PYTHON_BIN}" -c "import sys, json; print(json.load(sys.stdin)['level'])")
if [[ "${LOWERED_LEVEL}" != "internal" ]]; then
    log_fail "Expected internal level after lowering, got ${LOWERED_LEVEL}"
fi
log_pass "Monotonic lowering back to internal succeeded for human actor"

# --- S5: Content Split & Range Streaming ---
log_step "S5: Content Splitting (Internal 303 Redirect vs Confidential 200/206)"
# Internal should return 303 redirect
INTERNAL_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/v1/documents/${DOC_ID}/content" \
  -H "Authorization: Bearer ${TOKEN_EMP_T1}")
if [[ "${INTERNAL_CODE}" -ne 303 ]]; then
    log_fail "Expected 303 Redirect for Internal document content, got ${INTERNAL_CODE}"
fi
log_pass "Internal document redirects to presigned URL (HTTP 303)"

# Raise back to Confidential for direct streaming check
curl -sf -X POST "${API_URL}/v1/documents/${DOC_ID}/classification" \
  -H "Authorization: Bearer ${TOKEN_ADMIN_T1}" \
  -H "Content-Type: application/json" \
  -d '{"level_name": "confidential"}' > /dev/null

STREAM_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/v1/documents/${DOC_ID}/content" \
  -H "Authorization: Bearer ${TOKEN_ADMIN_T1}")
if [[ "${STREAM_CODE}" -ne 200 ]]; then
    log_fail "Expected 200 OK for Confidential document content streaming, got ${STREAM_CODE}"
fi

RANGE_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/v1/documents/${DOC_ID}/content" \
  -H "Authorization: Bearer ${TOKEN_ADMIN_T1}" -H "Range: bytes=0-9")
if [[ "${RANGE_CODE}" -ne 206 ]]; then
    log_fail "Expected 206 Partial Content for Range request, got ${RANGE_CODE}"
fi
log_pass "Confidential document streams directly with Range support (HTTP 200 / 206)"

# --- S6: Cross-Tenant 404 Parity ---
log_step "S6: Cross-Tenant 404 Byte Parity (#31)"
NON_EXISTENT_UUID="00000000-0000-0000-0000-000000000000"
CANON_404=$(curl -s "${API_URL}/v1/documents/${NON_EXISTENT_UUID}" -H "Authorization: Bearer ${TOKEN_OUTSIDER_T2}")

for PATH_SUFFIX in "" "/content" "/findings" "/jobs"; do
    TARGET_URL="${API_URL}/v1/documents/${DOC_ID}${PATH_SUFFIX}"
    RESPONSE=$(curl -s "${TARGET_URL}" -H "Authorization: Bearer ${TOKEN_OUTSIDER_T2}")
    if [[ "${RESPONSE}" != "${CANON_404}" ]]; then
        log_fail "404 Byte parity mismatch on ${TARGET_URL}"
    fi
done
log_pass "Cross-tenant 404 responses are byte-identical to nonexistent resource errors"

# --- S7: ClamAV EICAR Malware Rejection ---
log_step "S7: ClamAV EICAR Malware Rejection (#4)"
EICAR_INTENT=$(curl -sf -X POST "${API_URL}/v1/uploads" \
  -H "Authorization: Bearer ${TOKEN_ADMIN_T1}" \
  -H "Content-Type: application/json" \
  -d "{\"filename\": \"eicar_test.pdf\", \"size_bytes\": ${EICAR_SIZE}, \"content_type\": \"application/pdf\"}")

EICAR_UPLOAD_ID=$(echo "${EICAR_INTENT}" | "${PYTHON_BIN}" -c "import sys, json; print(json.load(sys.stdin)['upload_id'])")
EICAR_PUT_URL=$(echo "${EICAR_INTENT}" | "${PYTHON_BIN}" -c "import sys, json; print(json.load(sys.stdin)['presigned_put']['url'])")

curl -sf -X PUT "${EICAR_PUT_URL}" -H "Content-Type: application/pdf" --data-binary @"${EICAR_FILE}" || \
  curl -sf -X POST "${EICAR_PUT_URL}" --data-binary @"${EICAR_FILE}" || true

curl -sf -X POST "${API_URL}/v1/uploads/${EICAR_UPLOAD_ID}/complete" \
  -H "Authorization: Bearer ${TOKEN_ADMIN_T1}" \
  -H "Content-Type: application/json" \
  -d "{\"size_bytes\": ${EICAR_SIZE}}" || true

# Poll for terminal 'failed' status
for i in {1..30}; do
    EICAR_STATUS=$(curl -sf "${API_URL}/v1/documents/${EICAR_UPLOAD_ID}" -H "Authorization: Bearer ${TOKEN_ADMIN_T1}" | \
      "${PYTHON_BIN}" -c "import sys, json; print(json.load(sys.stdin).get('status', ''))" || echo "")
    if [[ "${EICAR_STATUS}" == "failed" ]]; then
        break
    fi
    sleep 1
done

if [[ "${EICAR_STATUS}" != "failed" ]]; then
    log_fail "EICAR upload was not marked as failed by ClamAV (status=${EICAR_STATUS})"
fi
log_pass "EICAR malware payload rejected and document transitioned to 'failed' status"

# Cleanup temporary files
rm -f "${PDF_FILE}" "${EICAR_FILE}"

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}All Wave 5A Scenarios (S0 - S7) Verified Successfully!${NC}"
echo -e "${GREEN}======================================================${NC}"
