"""Tests for classifier pipeline integration."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

from classifier.content_prep import truncate_content_by_pages
from classifier.metadata import (
    is_empty_classification,
    normalize_language,
    parse_document_date,
    resolve_date_for_tags,
    update_custom_fields,
)
from classifier.result import parse_classification_response
from classifier.tag_filters import (
    enrich_tags,
    filter_blacklisted_tags,
    filter_redundant_tags,
)
from classifier.taxonomy import TaxonomyCache

class TestClassificationPipelineIntegration:
    """Full classification data pipeline with real functions."""

    def test_full_pipeline_realistic_ocr_text(self):
        """
        Create realistic OCR text -> truncate -> parse LLM JSON -> filter tags
        -> enrich tags -> verify final tag list.
        """
        # Step 1: Build realistic multi-page OCR text
        pages = []
        for i in range(1, 6):
            pages.append(f"--- Page {i} ---")
            pages.append(f"This is the content of page {i}. It contains invoice details.")
        body = "\n\n".join(pages)
        footer = "\n\nTranscribed by model: gpt-5-mini"
        ocr_text = body + footer

        # Step 2: Truncate (should keep all 5 pages since max_pages > 5 isn't triggered)
        truncated, note = truncate_content_by_pages(
            ocr_text,
            max_pages=3,
            tail_pages=2,
            headerless_char_limit=15000,
        )

        # 5 pages, keeping 3 head + 2 tail = 5 total -> no truncation
        assert "Transcribed by model: gpt-5-mini" in truncated

        # Step 3: Parse a mock LLM JSON response
        llm_json = '''{
            "title": "Invoice #12345",
            "correspondent": "Acme Corp Ltd",
            "tags": ["invoice", "payment", "urgent", "AI", "New"],
            "document_date": "2025-06-15",
            "document_type": "Invoice",
            "language": "en",
            "person": "John Doe"
        }'''
        result = parse_classification_response(llm_json)

        assert result.title == "Invoice #12345"
        assert result.correspondent == "Acme Corp Ltd"
        assert result.document_type == "Invoice"
        assert len(result.tags) == 5

        # Step 4: Filter blacklisted tags ("AI" and "New" should be removed)
        filtered = filter_blacklisted_tags(result.tags)
        assert "AI" not in filtered
        assert "New" not in filtered
        assert "invoice" in filtered
        assert "payment" in filtered
        assert "urgent" in filtered

        # Step 5: Filter redundant tags (those matching correspondent/type/person)
        filtered = filter_redundant_tags(
            filtered,
            correspondent=result.correspondent,
            document_type=result.document_type,
            person=result.person,
        )
        # "invoice" matches document_type "Invoice" -> removed
        assert "invoice" not in filtered
        assert "payment" in filtered
        assert "urgent" in filtered

        # Step 6: Enrich tags (add model tags, year tag, country tag)
        enriched = enrich_tags(
            filtered,
            ocr_text,
            result.document_date,
            default_country_tag="DE",
            tag_limit=5,
        )

        # Model tag extracted from footer
        assert "gpt-5-mini" in enriched
        # Year tag from document_date
        assert "2025" in enriched
        # Country tag
        assert "de" in enriched  # enriched tags are lowercased
        # Original tags preserved (lowercased)
        assert "payment" in enriched
        assert "urgent" in enriched

    def test_pipeline_with_empty_result_detection(self):
        """Parse an empty classification result and detect it."""
        llm_json = '''{
            "title": "",
            "correspondent": "",
            "tags": [],
            "document_date": "",
            "document_type": "",
            "language": "",
            "person": ""
        }'''
        result = parse_classification_response(llm_json)
        assert is_empty_classification(result) is True

    def test_pipeline_with_null_fields(self):
        """LLM returns null fields which parse correctly."""
        llm_json = '''{
            "title": null,
            "correspondent": null,
            "tags": null,
            "document_date": null,
            "document_type": null,
            "language": null,
            "person": null
        }'''
        result = parse_classification_response(llm_json)
        assert result.title == ""
        assert result.tags == []
        assert is_empty_classification(result) is True

    def test_pipeline_with_markdown_wrapped_json(self):
        """LLM wraps response in markdown fences."""
        llm_response = '''Here is the classification:
```json
{
    "title": "Bank Statement",
    "correspondent": "Revolut",
    "tags": ["banking", "statement"],
    "document_date": "2025-03-01",
    "document_type": "Bank Statement",
    "language": "en",
    "person": ""
}
```'''
        result = parse_classification_response(llm_response)
        assert result.title == "Bank Statement"
        assert result.correspondent == "Revolut"
        assert len(result.tags) == 2

class TestTaxonomyCacheIntegration:
    """Test TaxonomyCache with a mock PaperlessClient."""

    def _make_mock_client(self):
        """Create a mock PaperlessClient with taxonomy items."""
        client = MagicMock()
        client.list_correspondents.return_value = [
            {"id": 1, "name": "Acme Corp", "document_count": 10},
            {"id": 2, "name": "Revolut", "document_count": 25},
            {"id": 3, "name": "Amazon", "document_count": 5},
        ]
        client.list_document_types.return_value = [
            {"id": 10, "name": "Invoice", "document_count": 50},
            {"id": 11, "name": "Bank Statement", "document_count": 30},
            {"id": 12, "name": "Receipt", "document_count": 15},
        ]
        client.list_tags.return_value = [
            {"id": 100, "name": "2025", "matching_algorithm": "none", "document_count": 40},
            {"id": 101, "name": "banking", "matching_algorithm": "none", "document_count": 20},
            {"id": 102, "name": "urgent", "matching_algorithm": "none", "document_count": 5},
        ]
        # Mock creation endpoints
        _next_id = [200]

        def _create_tag(name, **kw):
            tag_id = _next_id[0]
            _next_id[0] += 1
            return {"id": tag_id, "name": name, "matching_algorithm": "none"}

        def _create_correspondent(name, **kw):
            corr_id = _next_id[0]
            _next_id[0] += 1
            return {"id": corr_id, "name": name}

        client.create_tag.side_effect = _create_tag
        client.create_correspondent.side_effect = _create_correspondent
        client.create_document_type.side_effect = lambda name, **kw: {"id": 300, "name": name}
        return client

    def test_refresh_and_resolve_existing_correspondent(self):
        """Refresh cache, then look up an existing correspondent."""
        client = self._make_mock_client()
        cache = TaxonomyCache(client, taxonomy_limit=100)
        cache.refresh()

        # Look up existing correspondent by exact name
        corr_id = cache.get_or_create_correspondent_id("Acme Corp")
        assert corr_id == 1

        # No creation call should have been made
        client.create_correspondent.assert_not_called()

    def test_resolve_correspondent_with_suffix_matching(self):
        """'Revolut Ltd' should match existing 'Revolut' via substring."""
        client = self._make_mock_client()
        cache = TaxonomyCache(client, taxonomy_limit=100)
        cache.refresh()

        corr_id = cache.get_or_create_correspondent_id("Revolut Ltd")
        assert corr_id == 2
        client.create_correspondent.assert_not_called()

    def test_create_new_correspondent(self):
        """A new correspondent name triggers creation."""
        client = self._make_mock_client()
        cache = TaxonomyCache(client, taxonomy_limit=100)
        cache.refresh()

        corr_id = cache.get_or_create_correspondent_id("New Company GmbH")
        assert corr_id is not None
        client.create_correspondent.assert_called_once()

    def test_resolve_existing_and_create_new_tags(self):
        """Mix of existing and new tags: existing resolved, new created."""
        client = self._make_mock_client()
        cache = TaxonomyCache(client, taxonomy_limit=100)
        cache.refresh()

        tag_names = ["2025", "banking", "new-category", "another-new"]
        tag_ids = cache.get_or_create_tag_ids(tag_names)

        assert len(tag_ids) == 4
        # Existing tags resolved to their IDs
        assert 100 in tag_ids  # "2025"
        assert 101 in tag_ids  # "banking"
        # New tags created (with incrementing mock IDs)
        assert client.create_tag.call_count == 2

    def test_prompt_context_names_sorted_by_usage(self):
        """Top names returned for prompt context are sorted by usage."""
        client = self._make_mock_client()
        cache = TaxonomyCache(client, taxonomy_limit=100)
        cache.refresh()

        correspondents = cache.correspondent_names()
        # Revolut (25) should come before Acme Corp (10) and Amazon (5)
        assert correspondents[0] == "Revolut"
        assert "Acme Corp" in correspondents
        assert "Amazon" in correspondents

        doc_types = cache.document_type_names()
        assert doc_types[0] == "Invoice"  # 50 uses

    def test_resolve_existing_document_type(self):
        """Existing document type is resolved by name."""
        client = self._make_mock_client()
        cache = TaxonomyCache(client, taxonomy_limit=100)
        cache.refresh()

        type_id = cache.get_or_create_document_type_id("Invoice")
        assert type_id == 10
        client.create_document_type.assert_not_called()

    def test_empty_name_returns_none(self):
        """Empty correspondent or type name returns None."""
        client = self._make_mock_client()
        cache = TaxonomyCache(client, taxonomy_limit=100)
        cache.refresh()

        assert cache.get_or_create_correspondent_id("") is None
        assert cache.get_or_create_correspondent_id("   ") is None
        assert cache.get_or_create_document_type_id("") is None


class TestMetadataPipelineIntegration:
    """Real metadata functions working together on realistic data."""

    def test_full_metadata_pipeline(self):
        """Parse date, normalize language, update custom fields together."""
        # Parse a valid date
        parsed_date = parse_document_date("2025-06-15")
        assert parsed_date == "2025-06-15"

        # Resolve date for tags (prefers parsed date)
        tag_date = resolve_date_for_tags(parsed_date, "2024-01-01")
        assert tag_date == "2025-06-15"

        # Normalize language
        lang = normalize_language("en-US")
        assert lang == "en"

        # Update custom fields (upsert a person field)
        existing_fields = [
            {"field": 1, "value": "old-value"},
            {"field": 2, "value": "keep-this"},
        ]
        updated = update_custom_fields(existing_fields, field_id=1, value="John Doe")
        assert len(updated) == 2
        assert updated[0] == {"field": 1, "value": "John Doe"}
        assert updated[1] == {"field": 2, "value": "keep-this"}

    def test_metadata_pipeline_with_missing_date(self):
        """Empty date falls back to existing document date."""
        parsed_date = parse_document_date("")
        assert parsed_date is None

        # Falls back to existing date
        tag_date = resolve_date_for_tags(None, "2024-03-20")
        assert tag_date == "2024-03-20"

    def test_metadata_pipeline_with_invalid_date(self):
        """Invalid date string is rejected gracefully."""
        parsed_date = parse_document_date("not-a-date")
        assert parsed_date is None

        # Falls back to today when both dates are invalid
        tag_date = resolve_date_for_tags(None, None)
        assert tag_date == dt.date.today().isoformat()

    def test_normalize_language_variants(self):
        """Various language string formats are normalized correctly."""
        assert normalize_language("en") == "en"
        assert normalize_language("EN") == "en"
        assert normalize_language("pt-BR") == "pt"
        assert normalize_language("de_AT") == "de"
        assert normalize_language("und") == "und"
        assert normalize_language("") is None
        assert normalize_language("invalid-long-string") == "und"

    def test_custom_fields_append_when_new(self):
        """A new field ID is appended to the custom fields list."""
        existing = [{"field": 1, "value": "existing"}]
        updated = update_custom_fields(existing, field_id=5, value="new-person")
        assert len(updated) == 2
        assert updated[1] == {"field": 5, "value": "new-person"}

    def test_custom_fields_with_none_existing(self):
        """None existing fields produces a new list with one entry."""
        updated = update_custom_fields(None, field_id=3, value="test")
        assert updated == [{"field": 3, "value": "test"}]

    def test_date_with_time_component(self):
        """ISO date with time component is parsed correctly."""
        parsed = parse_document_date("2025-06-15T14:30:00Z")
        assert parsed == "2025-06-15"
