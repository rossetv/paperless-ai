"""OCR daemon: transcribes Paperless-ngx document pages with a vision model.

Polls for documents carrying the OCR queue tag, transcribes each page and writes
the assembled text back. All state lives in Paperless tags, so several instances
can run side by side.
"""
