# Fix gallery seed restore and diagnose live image generation

## Goal

Restore missing public gallery assets and diagnose the live web image generation failure with a real image request, not only pytest.

## What I already know

- User reports web image generation keeps waiting and returns errors.
- User clarified that “unit test” means running one real image generation request.
- Current SQLite has `gallery_items=3`, `gallery_assets=3`, `source='seed'=0`, `published + visible=1`.
- Static gallery seed still has 437 entries in `web/src/data/gallery-ui-seed.json` and 437 dimensions.
- `/api/gallery/public?limit=300` currently returns 1 item and 1 asset.
- `tests/test_gallery_service.py` passed, so current tests do not cover existing user submissions without seed rows.
- Full pytest currently has 3 unrelated failures in `tests/test_chat_image_migration.py` from config mock drift around `image_generation_max_account_attempts`.
- Previous real matrix image request failed after 4 account attempts with `download image failed`.

## Assumptions

- Existing user-submitted gallery rows must be preserved.
- Seed restore should be additive and idempotent.
- Admin approving a user-submitted item should append it to the published gallery, not replace seed assets or clear existing public items.
- No manual editing of `data/` unless done through application code or an explicit safe restore command after code is fixed.

## Requirements

- Run one real image generation request against the local app and capture queue/log evidence.
- Fix seed import so missing seed rows are restored even when non-seed gallery rows already exist.
- Preserve user-submitted gallery prompt and assets after admin approval.
- Make admin approval append to the public gallery rather than replacing the gallery set.
- Add tests for the regression where non-seed rows exist before seed import.
- Fix or account for the current image migration test mock failure if it blocks full pytest.

## Acceptance Criteria

- [ ] Real image generation request has a captured result or failure evidence with request id, queue status, and relevant logs.
- [ ] `GalleryService.list_public_items()` imports missing seed rows even if user submissions already exist.
- [ ] Existing user submissions remain in SQLite after seed restore.
- [ ] Approving a pending gallery item increases public item count by 1 and keeps existing public items.
- [ ] Gallery list responses still avoid returning legacy base64 data image bodies.
- [ ] Targeted gallery tests pass.
- [ ] Full pytest is either green or remaining failures are clearly unrelated and documented.

## Out of Scope

- Migrating old base64 gallery assets out of SQLite into files or object storage.
- Changing image model routing policy unless live evidence points there.
- Deleting or rewriting existing user gallery submissions.

## Technical Notes

- `services/gallery_service.py` currently skips seed import when any gallery row exists.
- `llmdoc/architecture/backend-api.md` currently says seed import only happens when gallery table is empty; this behavior is now too weak.
- `llmdoc/architecture/image-generation-flow.md` says real failures should be inspected through queue state, request records, and proxy/upstream logs.


## Addendum: Image History Loading

- Always load only the first 10 image conversation summaries when opening the image page history sidebar.
- Avoid full local history normalization or full migration during sidebar summary loading.
- `GET /api/image-conversations` should accept a bounded `limit` parameter.

## Additional Acceptance Criteria

- [x] Sidebar summary load calls `summary=true&limit=10`.
- [x] Server list query applies bounded SQL `LIMIT`.
- [x] Local fallback summary read is capped to 10 items and does not trigger full migration.
