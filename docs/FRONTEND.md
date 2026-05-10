# Frontend Notes

## Live Captions
- Future FE should show browser speech-recognition captions immediately while the user speaks English.
- FE should optionally connect to `WS /transcriptions/live?language=en&content_type=audio/webm`.
- If backend WS fails or is unavailable, FE should keep browser captions as fallback.
- Display source priority: `backend_ws > browser_speech_recognition > none`.
- Current backend WS is batch-on-commit: send binary audio chunks, then `{"type":"commit"}`.
- Backend WS returns `ready`, chunk `ack`, then `final` with the stored transcript shape.
- Canonical persisted transcript should still come from backend output, not interim browser captions.
