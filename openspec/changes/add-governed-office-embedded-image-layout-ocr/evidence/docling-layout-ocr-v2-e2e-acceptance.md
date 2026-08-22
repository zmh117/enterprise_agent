# Docling layout OCR v2 E2E acceptance

Date: 2026-08-21

This evidence intentionally records only governed identities, immutable profile
facts, terminal states, counts, representation kinds, and sanitized error codes.
It does not contain file names, document text, OCR text, coordinates, object
keys, provider response bodies, credentials, or other business content.

## User acceptance

The user reported that the real DOCX acceptance flow passed after activating the
new v2 Publication. The observed platform facts below corroborate the governed
processing, Runtime materialization, and Delivery portions of that acceptance.

## Frozen Publication

- Application: `assist03`
- Environment: `local`
- Active Publication revision: `24`
- Profile code/version: `docling-layout-ocr-v2` / `2`
- Profile hash:
  `c3f6d45b3d23f70727e047158f20b1e798fa9a6d188aa11b8985385a1bc79cb8`

## Fresh jobs and Runtime boundary

- Fresh v2 jobs:
  - `job_5b76f30191d54cd48f8a2faa54485058`: `SUCCEEDED`
  - `job_35d0a3f5d95f4007a8b04b94c27f7775`: `SUCCEEDED`
  - `job_dec2c43e50d94ef7935a9b8de89c66bf`: `SUCCEEDED`
- The DOCX snapshot entries for the completed follow-up jobs froze
  `representation_kind=MARKDOWN`; neither Docling JSON nor OCR Layout JSON was
  selected for Runtime materialization.
- The latest Runtime materialization transfer for
  `job_dec2c43e50d94ef7935a9b8de89c66bf` reached `CONSUMED`.

## Parent, picture, assembly, and representations

- Processing run:
  `file_processing_run_e58c30e3b0ec4f909a80deeb302666d8`
- Frozen Profile: `docling-layout-ocr-v2`
- Parent status: `PARTIAL`
- Stage/assembly: `ASSEMBLING` / `COMPLETED`
- Picture items: 8 total; 7 `AVAILABLE`, 1 `FAILED`, 0 failures caused by
  missing confidence.
- The remaining sanitized failure is
  `docling_picture_provenance_invalid`, preserving the v2 fail-closed structural
  boundary.
- Available immutable representations:
  `MARKDOWN`, `DOCLING_JSON`, and `OCR_LAYOUT_JSON`.
- All three fresh v2 jobs have a successful governed Delivery attempt for the
  exact source file/version.

## Contract conclusion

The v2 flow no longer converts the seven otherwise valid picture results into
whole-picture failures when Docling 1.30.0 omits per-block confidence. Missing
confidence is represented by the v2 nullable contract, while the independently
malformed provenance remains a sanitized, explicit partial failure. The user
accepted the Agent-visible result and original-file Delivery.

## Final verification

- `openspec validate add-governed-office-embedded-image-layout-ocr --strict`:
  passed.
- `git diff --check`: passed.
- The change task list is complete after recording this fresh acceptance.
