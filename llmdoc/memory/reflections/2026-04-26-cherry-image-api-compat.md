# 2026-04-26 Cherry Studio image API compatibility

## Context

- Web image generation worked, but Cherry Studio still reported `TypeError: Failed to fetch`.
- The failing client used the OpenAI Images API shape: `POST /v1/images/generations` with `model=gpt-image-2` and `response_format=url`.
- The fix is on branch `fix/cherry-image-api-compat`, commit `cb4cbae`.

## Lesson

- Do not treat a working `/image` page as proof that third-party API clients work.
- Test the exact third-party request body, including `response_format`, CORS preflight, Windows access to `127.0.0.1:3002`, and the second fetch of the returned image URL.
- For `response_format=url`, returning a `data:image/*;base64,...` string can still fail in Electron clients. Return an HTTP URL that the client can fetch without Authorization.
- After backend API changes, rebuild the local compose service before judging runtime behavior. A stale container can still return old `404` results.

## Promoted facts

- `POST /v1/images/generations` and `POST /v1/images/edits` are public compatibility entries again.
- Both entries share `generate_image_payload`, the image queue, account selection, retry behavior, and user key billing.
- `response_format=url` stores generated images under `data/generated_images/` and returns `/v1/images/generated/{image_id}`.
- `GET /v1/images/generated/{image_id}` does not require Authorization, so Cherry Studio can fetch the generated image after the JSON response.
- Verified locally with Cherry-style request: POST returned `200`, returned URL fetched with `200`, and the image bytes started with the PNG header.
