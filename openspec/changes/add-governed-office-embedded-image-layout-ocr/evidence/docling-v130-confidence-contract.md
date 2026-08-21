# Docling 1.30.0 picture confidence contract evidence

Date: 2026-08-21

This evidence records only processing states, counts, fixed component versions, HTTP outcomes, and safe error codes. It excludes source names, OCR text, coordinates, image bytes, object keys, credentials, external task identities, and message content.

## Fresh DOCX observation

- Frozen profile: `docling-layout-ocr-v1`.
- Parent result: `PARTIAL`.
- Embedded picture occurrences: 8.
- Parent Office conversion, referenced-picture extraction, bounded picture asset transfer, per-picture Docling submission/poll/result fetch, and final assembly all completed their HTTP exchanges successfully.
- Every per-picture Docling result fetch returned HTTP 200.
- Terminal picture outcomes recorded by the platform adapter:
  - 7 `FAILED` with `docling_picture_confidence_missing`.
  - 1 `FAILED` with `docling_picture_result_invalid`.
- Docling service logs included an independent RapidOCR empty-detection warning during the run, while the platform stored only safe terminal error codes.

## Contract conclusion

The fixed Docling 1.30.0 JSON contract does not guarantee a numeric `confidence` on every `DoclingDocument.texts[*]` item. Requiring it in picture-result v1 converts otherwise usable OCR text and provenance into a platform failure. The correction therefore requires a new immutable profile/schema version whose per-block confidence is nullable; it must not invent a value or modify the frozen v1 hash.

An unambiguous Docling `success` response with no errors and empty Markdown is a successful `NO_TEXT` outcome for v2. Non-empty results still require valid page size, text item, provenance, bbox, and coordinate origin and fail closed with safe structural error categories.
