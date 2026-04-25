from __future__ import annotations

import base64
import sys
import unittest
from io import BytesIO
from unittest.mock import patch

sys.modules.setdefault("pybase64", base64)

from services import image_service
from services.uploaded_image_service import uploaded_image_service
from PIL import Image, ImageDraw


class FakeSession:
    def close(self) -> None:
        return None

    def post(self, *_args, **_kwargs):
        raise AssertionError("unexpected post call")

    def put(self, *_args, **_kwargs):
        raise AssertionError("unexpected put call")

    def get(self, *_args, **_kwargs):
        raise AssertionError("unexpected get call")


class FakeSseResponse:
    def __init__(self, lines: list[str]):
        self.lines = list(lines)
        self.read_count = 0

    def iter_lines(self):
        for line in self.lines:
            self.read_count += 1
            yield line


class FakeOkResponse:
    ok = True
    status_code = 200
    text = ""

    def iter_lines(self):
        return iter([])


class ImageServiceAttachmentTests(unittest.TestCase):
    def test_build_uploaded_input_image_supports_data_url(self) -> None:
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
        )

        class Response:
            def __init__(self, *, ok: bool = True, payload: dict | None = None, status_code: int = 200, text: str = ""):
                self.ok = ok
                self._payload = payload or {}
                self.status_code = status_code
                self.text = text

            def json(self) -> dict:
                return dict(self._payload)

        class Session(FakeSession):
            def __init__(self) -> None:
                self.post_calls: list[tuple[str, dict | None]] = []
                self.put_calls: list[tuple[str, bytes, dict[str, str] | None]] = []

            def post(self, url: str, headers: dict | None = None, json: dict | None = None, timeout: int = 60) -> Response:
                del headers, timeout
                self.post_calls.append((url, json))
                if url.endswith("/backend-api/files"):
                    return Response(payload={"file_id": "file-upload-1", "upload_url": "https://upload.example.com/blob"})
                if url.endswith("/backend-api/files/file-upload-1/uploaded"):
                    return Response(payload={"status": "success"})
                raise AssertionError(f"unexpected post url: {url}")

            def put(
                self,
                url: str,
                data: bytes | None = None,
                headers: dict[str, str] | None = None,
                timeout: int = 120,
            ) -> Response:
                del timeout
                self.put_calls.append((url, data or b"", headers))
                return Response(status_code=201)

        session = Session()
        uploaded = image_service._build_uploaded_input_image(
            session,
            "token-123",
            "device-1",
            "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii"),
        )

        self.assertEqual(uploaded.file_id, "file-upload-1")
        self.assertEqual(uploaded.mime_type, "image/png")
        self.assertEqual(uploaded.size_bytes, len(png_bytes))
        self.assertEqual(uploaded.width, 1)
        self.assertEqual(uploaded.height, 1)
        self.assertEqual(session.post_calls[0][0], "https://chatgpt.com/backend-api/files")
        self.assertEqual(session.post_calls[0][1]["use_case"], "multimodal")
        self.assertEqual(session.put_calls[0][0], "https://upload.example.com/blob")
        self.assertEqual(session.put_calls[0][1], png_bytes)
        self.assertEqual(session.put_calls[0][2]["content-type"], "image/png")

    def test_build_conversation_message_uses_multimodal_text_with_attachment(self) -> None:
        with patch.object(
            image_service,
            "_build_uploaded_input_image",
            return_value=image_service.UploadedInputImage(
                file_id="file-input-1",
                file_name="input.png",
                mime_type="image/png",
                size_bytes=321,
                width=512,
                height=256,
            ),
        ):
            message = image_service._build_conversation_message(
                FakeSession(),
                "token-123",
                "device-1",
                "edit this image",
                input_images=[{"type": "input_image", "image_url": "https://example.com/source.png"}],
            )

        self.assertEqual(message["author"]["role"], "user")
        self.assertEqual(message["content"]["content_type"], "text")
        self.assertEqual(message["content"]["parts"], ["edit this image"])
        self.assertEqual(
            message["metadata"]["attachments"],
            [
                {
                    "id": "file-input-1",
                    "name": "input.png",
                    "mimeType": "image/png",
                    "size": 321,
                    "width": 512,
                    "height": 256,
                }
            ],
        )
        self.assertNotIn("attachments", message["content"])

    def test_build_uploaded_input_image_supports_local_file_id(self) -> None:
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
        )

        class Response:
            def __init__(self, *, ok: bool = True, payload: dict | None = None, status_code: int = 200, text: str = ""):
                self.ok = ok
                self._payload = payload or {}
                self.status_code = status_code
                self.text = text

            def json(self) -> dict:
                return dict(self._payload)

        class Session(FakeSession):
            def __init__(self) -> None:
                self.post_calls: list[tuple[str, dict | None]] = []
                self.put_calls: list[tuple[str, bytes, dict[str, str] | None]] = []

            def post(self, url: str, headers: dict | None = None, json: dict | None = None, timeout: int = 60) -> Response:
                del headers, timeout
                self.post_calls.append((url, json))
                if url.endswith("/backend-api/files"):
                    return Response(payload={"file_id": "file-upload-2", "upload_url": "https://upload.example.com/blob"})
                if url.endswith("/backend-api/files/file-upload-2/uploaded"):
                    return Response(payload={"status": "success"})
                raise AssertionError(f"unexpected post url: {url}")

            def put(
                self,
                url: str,
                data: bytes | None = None,
                headers: dict[str, str] | None = None,
                timeout: int = 120,
            ) -> Response:
                del timeout
                self.put_calls.append((url, data or b"", headers))
                return Response(status_code=201)

        session = Session()
        with patch.object(
            uploaded_image_service,
            "read_bytes",
            return_value=(
                png_bytes,
                {"mime_type": "image/png"},
            ),
        ), patch.object(
            uploaded_image_service,
            "consume_upload",
            return_value={"file_id": "upload-local-1"},
        ):
            uploaded = image_service._build_uploaded_input_image(
                session,
                "token-123",
                "device-1",
                {"file_id": "upload-local-1", "owner_auth_token": "test-auth-key"},
            )

        self.assertEqual(uploaded.file_id, "file-upload-2")
        self.assertEqual(uploaded.mime_type, "image/png")
        self.assertEqual(uploaded.size_bytes, len(png_bytes))
        self.assertEqual(session.put_calls[0][1], png_bytes)

    def test_build_conversation_message_surfaces_upload_failure(self) -> None:
        with patch.object(
            image_service,
            "_build_uploaded_input_image",
            side_effect=image_service.ImageGenerationError("failed to fetch input image"),
        ):
            with self.assertRaises(image_service.ImageGenerationError) as raised:
                image_service._build_conversation_message(
                    FakeSession(),
                    "token-123",
                    "device-1",
                    "edit this image",
                    input_images=[{"type": "input_image", "image_url": "https://example.com/source.png"}],
                )

        self.assertEqual(str(raised.exception), "failed to fetch input image")

    def test_gpt_image_2_uses_real_upstream_model(self) -> None:
        upstream_model, reasoning_effort = image_service._resolve_upstream_target("token-123", "gpt-image-2")

        self.assertEqual(upstream_model, "gpt-image-2")
        self.assertIsNone(reasoning_effort)

    def test_needs_text_render_retry_detects_oversized_or_unbalanced_text(self) -> None:
        good = Image.new("RGB", (512, 512), "black")
        good_draw = ImageDraw.Draw(good)
        good_draw.rectangle((120, 205, 392, 295), fill="white")
        good_bytes = BytesIO()
        good.save(good_bytes, format="PNG")

        bad = Image.new("RGB", (512, 512), "black")
        bad_draw = ImageDraw.Draw(bad)
        bad_draw.rectangle((36, 200, 476, 368), fill="white")
        bad_bytes = BytesIO()
        bad.save(bad_bytes, format="PNG")

        prompt = "black background with white letters ABCD"
        self.assertFalse(image_service._needs_text_render_retry(prompt, good_bytes.getvalue()))
        self.assertTrue(image_service._needs_text_render_retry(prompt, bad_bytes.getvalue()))

    def test_needs_text_render_retry_detects_extra_artifact_blocks(self) -> None:
        image = Image.new("RGB", (512, 512), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle((120, 205, 392, 295), fill="white")
        draw.rectangle((160, 350, 230, 382), fill="white")
        image_bytes = BytesIO()
        image.save(image_bytes, format="PNG")

        prompt = "black background with white letters ABCD"
        self.assertTrue(image_service._needs_text_render_retry(prompt, image_bytes.getvalue()))

    def test_refine_prompt_for_text_rendering_only_applies_to_text_prompts(self) -> None:
        plain_prompt = "a red apple on a wooden table"
        text_prompt = "black background with white letters ABCD"

        self.assertEqual(image_service._refine_prompt_for_text_rendering(plain_prompt), plain_prompt)
        refined = image_service._refine_prompt_for_text_rendering(text_prompt)
        self.assertIn("Keep one centered line only", refined)
        self.assertIn("No blur, glow, bloom", refined)
        self.assertTrue(refined.startswith(text_prompt))

    def test_generate_image_result_skips_prompt_refinement_when_input_image_exists(self) -> None:
        with (
            patch.object(image_service, "_new_session", return_value=(FakeSession(), {"oai-device-id": "device-1"})),
            patch.object(image_service, "_resolve_upstream_target", return_value=("gpt-image-2", None)),
            patch.object(image_service, "_bootstrap", return_value="device-1"),
            patch.object(image_service, "_chat_requirements", return_value=("chat-token", {})),
            patch.object(image_service, "_send_conversation", return_value=object()) as send_conversation,
            patch.object(
                image_service,
                "_parse_sse",
                return_value={
                    "conversation_id": "conv-input-1",
                    "file_ids": ["file-5"],
                    "text": "",
                },
            ),
            patch.object(image_service, "_fetch_download_url", return_value="https://example.com/5"),
            patch.object(image_service, "_download_image_payload", return_value=("aW1hZ2UtNQ==", "image/png")),
        ):
            image_service.generate_image_result(
                "token-123",
                "black background with white letters ABCD",
                model="gpt-image-2",
                n=1,
                input_images=[{"type": "input_image", "file_id": "upload_1", "owner_auth_token": "test-auth-key"}],
            )

        sent_prompt = send_conversation.call_args.args[6]
        self.assertEqual(sent_prompt, "black background with white letters ABCD")

    def test_generate_image_result_returns_all_upstream_attachments(self) -> None:
        with (
            patch.object(image_service, "_new_session", return_value=(FakeSession(), {"oai-device-id": "device-1"})),
            patch.object(image_service, "_resolve_upstream_target", return_value=("auto", None)),
            patch.object(image_service, "_bootstrap", return_value="device-1"),
            patch.object(image_service, "_chat_requirements", return_value=("chat-token", {})),
            patch.object(image_service, "_send_conversation", return_value=object()),
            patch.object(
                image_service,
                "_parse_sse",
                return_value={
                    "conversation_id": "conv-1",
                    "file_ids": ["file-1", "file-2"],
                    "text": "",
                },
            ),
            patch.object(image_service, "_fetch_download_url", side_effect=["https://example.com/1", "https://example.com/2"]),
            patch.object(
                image_service,
                "_download_image_payload",
                side_effect=[
                    ("aW1hZ2UtMQ==", "image/png"),
                    ("aW1hZ2UtMg==", "image/webp"),
                ],
            ),
        ):
            payload = image_service.generate_image_result("token-123", "draw two apples", model="gpt-image-1", n=1)

        self.assertEqual(len(payload["data"]), 2)
        self.assertEqual(payload["data"][0]["b64_json"], "aW1hZ2UtMQ==")
        self.assertEqual(payload["data"][0]["mime_type"], "image/png")
        self.assertEqual(payload["data"][1]["b64_json"], "aW1hZ2UtMg==")
        self.assertEqual(payload["data"][1]["mime_type"], "image/webp")

    def test_generate_image_result_retries_when_sse_stream_breaks_once(self) -> None:
        parse_calls = {"count": 0}

        def parse_once_then_succeed(_response: object) -> dict[str, object]:
            parse_calls["count"] += 1
            if parse_calls["count"] == 1:
                raise Exception("curl: (92) HTTP/2 stream 1 was not closed cleanly: INTERNAL_ERROR (err 2)")
            return {
                "conversation_id": "conv-2",
                "file_ids": ["file-3"],
                "text": "",
            }

        with (
            patch.object(image_service, "_new_session", return_value=(FakeSession(), {"oai-device-id": "device-1"})),
            patch.object(image_service, "_resolve_upstream_target", return_value=("auto", None)),
            patch.object(image_service, "_bootstrap", return_value="device-1"),
            patch.object(image_service, "_chat_requirements", return_value=("chat-token", {})),
            patch.object(image_service, "_send_conversation", return_value=object()),
            patch.object(image_service, "_parse_sse", side_effect=parse_once_then_succeed),
            patch.object(image_service, "_fetch_download_url", return_value="https://example.com/3"),
            patch.object(image_service, "_download_image_payload", return_value=("aW1hZ2UtMw==", "image/png")),
        ):
            payload = image_service.generate_image_result("token-123", "draw ABCD", model="gpt-image-1", n=1)

        self.assertEqual(parse_calls["count"], 2)
        self.assertEqual(len(payload["data"]), 1)
        self.assertEqual(payload["data"][0]["b64_json"], "aW1hZ2UtMw==")

    def test_parse_sse_returns_after_image_file_id_and_conversation_id(self) -> None:
        response = FakeSseResponse(
            [
                'data: {"conversation_id":"conv-fast","message":{"content":{"content_type":"text","parts":["working"]}}}',
                'data: {"conversation_id":"conv-fast","message":{"metadata":{"attachments":[{"id":"file-service://file-ready"}]}}}',
                'data: {"conversation_id":"conv-fast","type":"message_stream_complete"}',
                'data: {"conversation_id":"conv-fast","message":{"content":{"content_type":"text","parts":["late"]}}}',
            ]
        )

        parsed = image_service._parse_sse(response)

        self.assertEqual(parsed["conversation_id"], "conv-fast")
        self.assertEqual(parsed["file_ids"], ["file-ready"])
        self.assertEqual(response.read_count, 2)

    def test_send_conversation_uses_f_conversation_for_images_route(self) -> None:
        class Session(FakeSession):
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def post(self, url: str, **kwargs):
                self.calls.append((url, kwargs.get("json") or {}))
                return FakeOkResponse()

        session = Session()
        with patch.object(
            image_service,
            "_build_conversation_message",
            return_value={
                "id": "msg-1",
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": ["draw"]},
                "metadata": {"attachments": []},
            },
        ):
            image_service._send_conversation(
                session,
                "token-123",
                "device-1",
                "chat-token",
                None,
                "parent-1",
                "draw",
                "auto",
                route="images",
            )

        self.assertEqual(session.calls[0][0], "https://chatgpt.com/backend-api/f/conversation")
        self.assertEqual(session.calls[0][1]["client_prepare_state"], "none")
        self.assertEqual(session.calls[0][1]["supported_encodings"], ["v1"])

    def test_send_responses_request_uses_codex_responses_endpoint(self) -> None:
        class Session(FakeSession):
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict, dict]] = []

            def post(self, url: str, **kwargs):
                self.calls.append((url, kwargs.get("headers") or {}, kwargs.get("json") or {}))
                return FakeOkResponse()

        session = Session()
        image_service._send_responses_request(
            session,
            "token-123",
            "account-123",
            "draw",
            "gpt-image-2",
            None,
        )

        url, headers, body = session.calls[0]
        self.assertEqual(url, "https://chatgpt.com/backend-api/codex/responses")
        self.assertEqual(headers["Chatgpt-Account-Id"], "account-123")
        self.assertEqual(body["model"], "gpt-5.4-mini")
        self.assertEqual(body["tools"][0]["type"], "image_generation")
        self.assertEqual(body["tools"][0]["model"], "gpt-image-2")
        self.assertEqual(body["tools"][0]["action"], "generate")

    def test_is_transient_image_error_treats_conversation_422_as_retryable(self) -> None:
        self.assertTrue(image_service.is_transient_image_error("conversation failed: 422"))

    def test_is_transient_image_error_treats_json_status_code_429_as_retryable(self) -> None:
        self.assertTrue(
            image_service.is_transient_image_error(
                '{"detail":{"message":"upstream rate limit","status_code":429}}'
            )
        )

    def test_is_transient_image_error_treats_cloudflare_code_string_as_retryable(self) -> None:
        self.assertTrue(
            image_service.is_transient_image_error(
                '{"error":{"code":"cf_bad_gateway","message":"temporarily unavailable"}}'
            )
        )

    def test_generate_image_result_retries_when_text_render_quality_is_rejected_once(self) -> None:
        with (
            patch.object(image_service, "_new_session", return_value=(FakeSession(), {"oai-device-id": "device-1"})),
            patch.object(image_service, "_resolve_upstream_target", return_value=("auto", None)),
            patch.object(image_service, "_bootstrap", return_value="device-1"),
            patch.object(image_service, "_chat_requirements", return_value=("chat-token", {})),
            patch.object(image_service, "_send_conversation", return_value=object()),
            patch.object(
                image_service,
                "_parse_sse",
                return_value={
                    "conversation_id": "conv-3",
                    "file_ids": ["file-4"],
                    "text": "",
                },
            ),
            patch.object(
                image_service,
                "_download_generated_images",
                side_effect=[
                    image_service.ImageGenerationError("low quality text render for file: file-4"),
                    [
                        image_service.GeneratedImage(
                            b64_json="aW1hZ2UtNA==",
                            revised_prompt="draw ABCD",
                            mime_type="image/png",
                        )
                    ],
                ],
            ) as download_mock,
        ):
            payload = image_service.generate_image_result("token-123", "draw white letters ABCD", model="gpt-image-1", n=1)

        self.assertEqual(download_mock.call_count, 2)
        self.assertEqual(payload["data"][0]["b64_json"], "aW1hZ2UtNA==")

    def test_download_image_payload_retries_until_content_arrives(self) -> None:
        class Response:
            def __init__(self, ok: bool, content: bytes, content_type: str = "image/png") -> None:
                self.ok = ok
                self.content = content
                self.headers = {"content-type": content_type}
                self.status_code = 200 if ok else 502

        class Session:
            def __init__(self) -> None:
                self.calls = 0

            def get(self, _url: str, timeout: int = 60) -> Response:
                self.calls += 1
                if self.calls < 3:
                    return Response(False, b"")
                return Response(True, b"\x89PNG\r\n\x1a\nrest")

        session = Session()
        payload, mime_type = image_service._download_image_payload(session, "https://example.com/image.png")

        self.assertEqual(session.calls, 3)
        self.assertEqual(mime_type, "image/png")
        self.assertEqual(base64.b64decode(payload), b"\x89PNG\r\n\x1a\nrest")


if __name__ == "__main__":
    unittest.main()
