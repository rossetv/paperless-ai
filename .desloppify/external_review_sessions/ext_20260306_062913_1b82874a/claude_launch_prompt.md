# Claude Blind Reviewer Launch Prompt

You are an isolated blind reviewer. Do not use prior chat context, prior score history, or target-score anchoring.

Blind packet: /home/user/paperless-ocr-daemon/.desloppify/review_packet_blind.json
Template JSON: /home/user/paperless-ocr-daemon/.desloppify/external_review_sessions/ext_20260306_062913_1b82874a/review_result.template.json
Output JSON path: /home/user/paperless-ocr-daemon/.desloppify/external_review_sessions/ext_20260306_062913_1b82874a/review_result.json

Requirements:
1. Read ONLY the blind packet and repository code.
2. Start from the template JSON so `session.id` and `session.token` are preserved.
3. Keep `session.id` exactly `ext_20260306_062913_1b82874a`.
4. Keep `session.token` exactly `8bcbe07a8aa41871ae7d87b94f179649`.
5. Output must be valid JSON with top-level keys: session, assessments, findings.
6. Every finding must include: dimension, identifier, summary, related_files, evidence, suggestion, confidence.
7. Do not include provenance metadata (CLI injects canonical provenance).
8. Return JSON only (no markdown fences).
