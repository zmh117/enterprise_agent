FROM quay.io/docling-project/docling-serve:v1.30.0@sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807

USER 0
COPY --chown=1001:0 backend/app/modules/document_processing/model_artifact.py /opt/enterprise-agent/verify_model_bundle.py
USER 1001
