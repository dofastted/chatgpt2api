# 2026-04-29 image inspiration rail

## Context

- The user wanted the `/image` page right-side "画廊灵感" rail to behave as a real waterfall inspiration rail, not only the standalone `/gallery` page.
- The first correction was to keep the change on `web/src/app/image/page.tsx` (`ImageInspirationRail`) and verify the actual page scroll container, not only the visual layout.
- The follow-up added a user action after successful image generation: each successful result can be added to the right-side rail.

## What changed

- `ImageInspirationRail` now lays out two explicit columns and auto-scrolls its own scroll viewport.
- Hovering the rail pauses auto-scroll. Leaving the rail starts a 3 second delay before scroll resumes.
- Generated success images show an "添加到瀑布流" button. After adding, the button becomes "已在瀑布流".
- User-added generated images were originally stored in `web/src/store/gallery-prompts.ts` under the current auth scope and rendered before seed gallery items as "我的作品".
- As of the 2026-05-05 gallery management update, gallery local storage uses a hashed auth scope instead of the raw key, generated images are saved locally first, and the same item is submitted to the backend review queue.
- Existing public gallery items still sort by prompt usage first, then by per-load random rank on the frontend; the public item source is now the backend gallery API with static seed as fallback.

## Verification

- `npm run lint` passed.
- `npm run build` passed.
- `docker compose -f docker-compose-local.yml up -d --build` rebuilt the local container.
- `http://127.0.0.1:3002/image` returned `200`.
- Chrome CDP page check confirmed the add button, the first rail item becoming "我的作品", duplicate prevention, auto-scroll movement, hover pause, and delayed resume.

## Lessons

- For this UI, "画廊" can mean two different surfaces: standalone `/gallery` and `/image` right-side "画廊灵感". Future changes should confirm which surface is meant before editing.
- Auto-scroll should be verified by reading the real DOM scroll viewport's `scrollTop`, `scrollHeight`, and `clientHeight`; a visual grid change alone does not prove the rail scrolls.
- User-specific gallery additions should remain separate from backend image conversation history. They may now create backend gallery review submissions, but that does not make image conversation history the gallery source of truth.
