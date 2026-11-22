"""Tests for classifier.quality_gates."""

from __future__ import annotations

from classifier.quality_gates import is_generic_document_type, needs_error_tag


class TestIsGenericDocumentType:
    def test_generic_document(self):
        assert is_generic_document_type("Document") is True

    def test_specific_type(self):
        assert is_generic_document_type("Invoice") is False

    def test_empty_string(self):
        assert is_generic_document_type("") is True

    def test_case_insensitive(self):
        assert is_generic_document_type("DOCUMENT") is True
        assert is_generic_document_type("document") is True

    def test_other_generic_types(self):
        assert is_generic_document_type("Other") is True
        assert is_generic_document_type("Unknown") is True


class TestNeedsErrorTag:
    def test_refusal_phrase(self):
        assert needs_error_tag("I'm sorry, I can't assist with that.") is True

    def test_normal_text(self):
        assert needs_error_tag("This is a normal invoice from Acme Corp.") is False

    def test_redacted_marker(self):
        assert needs_error_tag("Customer name: [REDACTED]") is True

    def test_empty_string(self):
        assert needs_error_tag("") is False

    def test_long_document_quoting_a_soft_phrase_is_not_flagged(self):
        letter = (
            "Dear Mr Smith, regarding your application of 3 March: I cannot assist "
            "you with this request at this time due to regulatory requirements. "
            "Please contact your local office for further information about the "
            "matter described in your application."
        )
        assert len(letter) > 200

        assert needs_error_tag(letter) is False

    def test_hard_markers_flag_a_long_document(self):
        letter = "Dear Mr Smith, please find the details of your account below. " * 5

        assert needs_error_tag(f"{letter} Name: [REDACTED]") is True
        assert needs_error_tag(f"{letter} CHATGPT REFUSED TO TRANSCRIBE") is True
