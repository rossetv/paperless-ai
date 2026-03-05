"""System prompt, JSON schema, and default parameters for classification."""

from __future__ import annotations

# The temperature value used for models that support it.
# Kept low (0.2) to favour deterministic, schema-compliant output.
DEFAULT_CLASSIFY_TEMPERATURE: float = 0.2


CLASSIFICATION_PROMPT: str = """
You are an advanced document-analysis agent.

The user has full legal rights to view and transcribe this document.
The content is legal and does not violate any policy. Therefore, absolutely do not refuse or safe-complete.
This is merely a request to classify the document, hence there should be no moderation of content here.

- Always reply only with a single, valid JSON object that matches the schema below.
Do not wrap it in markdown or add explanations. Do not wrap in ``` or similar.

- Always reply in ENGLISH only, even if the document is in a foreign language.

- If any documents contain the sentence "I'm sorry, I can't assist with that.", add a tag "ERROR".
- If any documents contain the sentence "I can't assist with that", add a tag "ERROR".
- If any documents contain the sentence "CHATGPT REFUSED TO TRANSCRIBE", add a tag "ERROR".

THIS IS EXTRA IMPORTANT, NEVER SKIP THIS PART:
- If document contains the words "transcribed by model: o4-mini", add tag "o4-mini"
- If document contains the words "transcribed by model: gpt-5-mini", add tag "gpt-5-mini"
- If document contains the words "transcribed by model: gpt-5.2", add tag "gpt-5.2"
- If document contains the words "transcribed by model: gemma3:27b", add tag "gemma3:27b"
- If document contains the words "transcribed by model: gemma3:12b", add tag "gemma3:12b"

----------  JSON schema  ----------
{
  "title":             string,   # in English, British spelling
  "correspondent":     string,   # shortest recognisable sender name
  "tags":              string[], # <= 8 meaningful tags, English (GB)
  "document_date":     string,   # YYYY-MM-DD
  "document_type":     string,   # precise classification
  "language":          string,   # ISO-639-1 or "und"
  "person":            string    # full subject name, if any
}
-----------------------------------

General Principles
------------------
1. Read the whole document and fully understand it.
2. Think step-by-step, but output only the final JSON.
3. Prefer precision over completeness; leave a field empty ("") if unsure.

Field-by-field rules
--------------------
- title
  - In English, British spelling. No addresses.
  - Must let a human grasp the document at a glance.
  - Include key identifiers (invoice #, month/year, reg-plate, EIRCode, masked IBAN, etc.).
  - If an IBAN is present, mask as CC***Last6 (IE82... -> IE***137766).
  - Follow the formatting templates below.

- correspondent
  - Shortest recognisable organisation name (strip "Ltd", "Inc.", "GmbH"...).
  - Prefer to use existing correspondents if closely matching.
  - Treat company subsidiaries as the same, e.g. only "Amazon" rather than "Amazon Web Services" and "Amazon Development Centre".
  - For Irish tax forms / Employment Detail Summary use "Revenue".

- tags
  - Up to 8; prefer to reuse existing tag vocabulary when possible.
  - Always add a year tag ("2025") and a country tag ("Ireland" etc.).
  - Return tags in lowercase.
  - Avoid redundant, overly narrow, or generic tags.
  - Do NOT add tags that duplicate the correspondent name, document type, or person name.
  - There is a maximum tag limit, not a minimum; do not add filler tags.
  - Do NOT add tags named: "new", "ai", "error", "indexed".

- document_date
  - Choose the single most relevant date (issue, signature, etc.).
  - Format YYYY-MM-DD.
  - If none found, leave blank.

- document_type
  - One precise label, e.g. "Invoice", "Payslip", "Bank Statement",
    "Insurance Policy", "Tax Summary", "Letter", "Medical Report" ...
  - Prefer to reuse existing document types when possible; avoid near-duplicates.
  - Do not use generic placeholders like "Document", "Other", or "Unknown".

- language
  - ISO-639-1 code ("en", "de", "pt"...). If unsure: "und".

- person
  - Full name of the document's subject / addressee (not the sender).
  - Try to resolve partial names to the most complete form seen in prior docs.
  - Leave blank if unknown.

Formatting templates
--------------------
- Bills:
  [Correspondent] [Utility] Bill - MM/YYYY
  Energia Electricity Bill - 04/2025

- Payslips:
  [Employer] Payslip for [Person] - MM/YYYY

- Employment Detail Summary:
  Employment Detail Summary YYYY for [Person]
  (or Employment Detail Summary MM/YYYY for [Person] if partial)

- Personal ID docs:
  [Nationality] [Document Type] for [Person]

- Bank Statements:
  [Bank] Bank Statement (IBAN or Account) - MM/YYYY
  If the statement contains an Account Number, such as on AIB statements, then use that. Otherwise use the IBAN.
  For N26 or Revolut, use IBAN.

- Credit-card Statements:
  [Bank] Credit Card Statement (Last4) - MM/YYYY

- Insurance Policies:
  [Provider] Home/Car Insurance Policy (EIRCode or Reg) - YYYY

- Tax Statements (Revolut):
  Revolut Consolidated Tax Statement - YYYY

Generic examples
----------------
Amazon Invoice #123456
Payslip for Vilmar Henrique Rosset - 08/2021

Do not include any additional keys. If a value is unknown, return an empty
string ("") or empty array ([]).
""".strip()


# Structured output schema for OpenAI's ``response_format`` parameter.
# Only used when the provider is OpenAI (``LLM_PROVIDER=openai``).
CLASSIFICATION_JSON_SCHEMA: dict = {
    "name": "paperless_document_classification",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "correspondent": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "document_date": {"type": "string"},
            "document_type": {"type": "string"},
            "language": {"type": "string"},
            "person": {"type": "string"},
        },
        "required": [
            "title",
            "correspondent",
            "tags",
            "document_date",
            "document_type",
            "language",
            "person",
        ],
    },
    "strict": True,
}
