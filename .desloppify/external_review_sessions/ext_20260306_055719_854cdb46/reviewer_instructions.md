# External Blind Review Session

Session id: ext_20260306_055719_854cdb46
Session token: 7e4e5847a166816333716d6bb993061f
Blind packet: /home/user/paperless-ocr-daemon/.desloppify/review_packet_blind.json
Template output: /home/user/paperless-ocr-daemon/.desloppify/external_review_sessions/ext_20260306_055719_854cdb46/review_result.template.json
Claude launch prompt: /home/user/paperless-ocr-daemon/.desloppify/external_review_sessions/ext_20260306_055719_854cdb46/claude_launch_prompt.md
Expected reviewer output: /home/user/paperless-ocr-daemon/.desloppify/external_review_sessions/ext_20260306_055719_854cdb46/review_result.json

Happy path:
1. Open the Claude launch prompt file and paste it into a context-isolated subagent task.
2. Reviewer writes JSON output to the expected reviewer output path.
3. Submit with the printed --external-submit command.

Reviewer output requirements:
1. Return JSON with top-level keys: session, assessments, findings.
2. session.id must be `ext_20260306_055719_854cdb46`.
3. session.token must be `7e4e5847a166816333716d6bb993061f`.
4. Include findings with required schema fields (dimension/identifier/summary/related_files/evidence/suggestion/confidence).
5. Use the blind packet only (no score targets or prior context).
