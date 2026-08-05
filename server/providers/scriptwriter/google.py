"""Google Gemini scriptwriter provider with rate limiting and retry."""

import logging
import re
from typing import Optional

import httpx

from server.providers.base import ScriptWriterProvider
from server.utils.rate_limiter import (
    NonRetryableError,
    RateLimiter,
    retry_with_backoff,
)

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.5-flash"

DEFAULT_SYSTEM_PROMPT = """You are a radio DJ. Write short, punchy DJ breaks.
Be brief — a few sentences at most. Get in, say something fun, get out.
Don't read lists — weave information in organically.
Match your energy to the time of day and the music that's been playing."""


def _clean_for_tts(text: str, truncated: bool = False) -> str:
    """Clean LLM output so it's safe for text-to-speech rendering.

    Strips markdown formatting, special characters, and — if the response
    was truncated — removes the last incomplete sentence so the DJ voice
    doesn't cut off mid-thought.

    Args:
        text: Raw script text from the LLM.
        truncated: Whether the LLM response hit the token limit.

    Returns:
        Cleaned text suitable for TTS.
    """
    # Strip markdown bold/italic markers
    text = re.sub(r'\*+', '', text)
    # Strip markdown headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Strip bullet point markers
    text = re.sub(r'^[\-\*•]\s+', '', text, flags=re.MULTILINE)
    # Strip parenthetical asides that TTS reads awkwardly
    text = re.sub(r'\([^)]*\)', '', text)
    # Collapse multiple spaces/newlines
    text = re.sub(r'\s+', ' ', text).strip()

    # Only trim when the text demonstrably ends mid-sentence: a response
    # that hit the token limit exactly at a sentence boundary is complete.
    if truncated and text and not text.endswith((".", "!", "?")):
        # The LLM was cut off — remove the last (incomplete) sentence.
        # Find the last sentence-ending punctuation and cut there.
        match = re.match(r'^(.*[.!?])\s+\S', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
            logger.warning(
                "Trimmed truncated script to last complete sentence"
            )
        else:
            # No complete sentence found — something is very wrong
            logger.error(
                "Truncated script had no complete sentence: %s", text[:100]
            )

    return text


class GeminiScriptWriterProvider(ScriptWriterProvider):
    """DJ script generation provider using Google's Gemini API.

    Generates natural-sounding DJ break scripts based on playback context.
    Rate-limited to avoid API throttling. Retries on transient failures.

    Args:
        api_key: Google AI Studio API key.
        model: Gemini model to use.
    """

    def __init__(
        self, api_key: str, model: str = DEFAULT_MODEL
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client: Optional[httpx.AsyncClient] = None
        self._rate_limiter = RateLimiter(
            calls_per_minute=15, min_interval=4.0, name="gemini_script"
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        Returns:
            An httpx.AsyncClient configured for the Gemini API.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=GEMINI_API_BASE,
                headers={
                    "Content-Type": "application/json",
                    # The key rides a header, never the URL, so it cannot
                    # leak through exception messages, logs, or health
                    # check error strings.
                    "x-goog-api-key": self._api_key,
                },
                timeout=60.0,
            )
        return self._client

    async def write_break(self, context: dict) -> dict:
        """Generate a DJ break script from playback context.

        Args:
            context: Dictionary containing recent tracks, announcements,
                station identity, and timing information.

        Returns:
            A dict with script_text, estimated_duration, and context snapshot.
        """
        return await retry_with_backoff(
            self._write_break_impl,
            context,
            max_retries=2,
            base_delay=5.0,
            max_delay=30.0,
            rate_limiter=self._rate_limiter,
            operation_name="gemini_write_break",
        )

    async def _write_break_impl(self, context: dict) -> dict:
        """Internal write_break implementation.

        Args:
            context: DJ break context dictionary.

        Returns:
            A dict with script_text, estimated_duration, and metadata.
        """
        client = self._get_client()

        # Build system prompt
        personality = context.get("personality_prompt", "")
        station_name = context.get("station_name", "AI Radio")
        dj_name = context.get("dj_name", "DJ")

        system_prompt = f"""{DEFAULT_SYSTEM_PROMPT}

Station: {station_name}
Your DJ name: {dj_name}
{f"Personality: {personality}" if personality else ""}

Rules:
- Keep it SHORT — a few sentences, not paragraphs. Less is more.
- Never read announcements as a list — weave them into conversation
- Don't ramble or pad with filler. Say it and move on.
- Target roughly 150 words per minute for TTS timing
- CRITICAL: This text goes directly to a text-to-speech engine. Write ONLY plain spoken words.
- Never use asterisks, markdown, bullet points, quotation marks, parentheses, or any special formatting.
- Never use abbreviations — write them out (e.g. "PM" should be written as the words you want spoken).
- Every sentence MUST be complete. Never leave a thought unfinished.
- If a current time is provided, use ONLY that time. Never guess or invent a different time. Use the exact time description given to you."""

        # Build user message with context
        max_duration = context.get("max_duration", 60)
        max_words = int((max_duration / 60) * 150)

        # Aim for ~60% of the absolute max to keep breaks tight
        target_words = int(max_words * 0.6)

        parts = [
            f"Generate a DJ break script. Keep it to around {target_words} words (absolute max {max_words}). Shorter is better."
        ]

        # Put time first so the LLM can't miss it
        current_time = context.get("current_time", "")
        if current_time and context.get("mention_time", True):
            parts.append(f"RIGHT NOW it is {current_time}. If you mention the time, you MUST say it is {current_time}. Do not use any other time.")

        recent_tracks = context.get("recent_tracks", [])
        if recent_tracks:
            track_lines = []
            for t in recent_tracks[-5:]:
                title = t.get("title", "Unknown")
                style = t.get("style", "")
                tags = t.get("tags", "")
                desc = title
                if style and tags:
                    desc += f" ({style} — {tags})"
                elif style:
                    desc += f" ({style})"
                elif tags:
                    desc += f" ({tags})"
                track_lines.append(f"  - {desc}")
            parts.append("Recently played:\n" + "\n".join(track_lines))

        announcements = context.get("announcements", [])
        if announcements:
            ann_lines = []
            for a in announcements:
                priority = a.get("priority", "normal")
                ann_lines.append(f"  - [{priority}] {a.get('text', '')}")
            parts.append(
                "Announcements to weave in:\n" + "\n".join(ann_lines)
            )

        user_message = "\n\n".join(parts)

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_message}],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 1024,
                "temperature": 0.9,
            },
        }

        try:
            logger.info("Generating DJ break script via Gemini")
            url = f"/models/{self._model}:generateContent"
            response = await client.post(url, json=payload)

            if response.status_code == 429:
                logger.warning("Gemini rate limited")
                raise RuntimeError("Gemini rate limited")

            response.raise_for_status()
            data = response.json()

            # Extract text from Gemini response
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("Gemini returned no candidates")

            content = candidates[0].get("content", {})
            parts_out = content.get("parts", [])
            if not parts_out:
                raise RuntimeError("Gemini returned empty response")

            # Check if the response was truncated
            finish_reason = candidates[0].get("finishReason", "")
            if finish_reason == "MAX_TOKENS":
                logger.warning(
                    "Gemini script hit token limit — output likely truncated"
                )

            raw_text = parts_out[0].get("text", "").strip()
            if not raw_text:
                raise RuntimeError("Gemini returned empty text")

            script_text = _clean_for_tts(raw_text, truncated=(finish_reason == "MAX_TOKENS"))

            if not script_text:
                raise RuntimeError("Gemini script was empty after cleaning")

            word_count = len(script_text.split())
            estimated_duration = (word_count / 150) * 60

            logger.info(
                "DJ break script generated via Gemini: %d words, ~%.0fs estimated",
                word_count,
                estimated_duration,
            )

            return {
                "script_text": script_text,
                "estimated_duration": estimated_duration,
                "word_count": word_count,
                "context": context,
                "model": self._model,
            }

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status >= 500:
                raise RuntimeError(
                    f"Gemini server error: {status}"
                ) from exc
            logger.error(
                "Gemini API error: %s %s",
                status,
                exc.response.text[:200],
            )
            if status in (400, 401, 403):
                raise NonRetryableError(f"Gemini API error: {status}") from exc
            raise RuntimeError(f"Gemini API error: {status}") from exc
        except httpx.RequestError as exc:
            logger.error("Gemini request failed: %s", exc)
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

    async def rewrite_prompt(self, prompt: str, instruction: str) -> str:
        """Rewrite a prompt using Gemini for creative variation.

        Args:
            prompt: The original prompt text.
            instruction: Rewriting guidance for the LLM.

        Returns:
            The rewritten prompt, or the original on failure.
        """
        try:
            return await retry_with_backoff(
                self._rewrite_prompt_impl,
                prompt,
                instruction,
                max_retries=1,
                base_delay=3.0,
                max_delay=10.0,
                rate_limiter=self._rate_limiter,
                operation_name="gemini_rewrite_prompt",
            )
        except Exception as exc:
            logger.warning("Prompt rewrite failed, using original: %s", exc)
            return prompt

    async def _rewrite_prompt_impl(
        self, prompt: str, instruction: str
    ) -> str:
        """Internal implementation for prompt rewriting.

        Args:
            prompt: The original prompt text.
            instruction: Rewriting guidance for the LLM.

        Returns:
            The rewritten prompt string.
        """
        client = self._get_client()

        payload = {
            "system_instruction": {
                "parts": [{"text": instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 200,
                "temperature": 0.9,
            },
        }

        url = f"/models/{self._model}:generateContent"
        try:
            response = await client.post(url, json=payload)

            if response.status_code == 429:
                raise RuntimeError("Gemini rate limited")

            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Wrap so the raw exception (which embeds the request URL)
            # never propagates into retry logs or API error strings.
            status = exc.response.status_code
            logger.error(
                "Gemini rewrite API error: %s %s",
                status,
                exc.response.text[:200],
            )
            if status in (400, 401, 403):
                raise NonRetryableError(f"Gemini API error: {status}") from exc
            raise RuntimeError(f"Gemini API error: {status}") from exc
        except httpx.RequestError as exc:
            logger.error("Gemini rewrite request failed: %s", exc)
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

        data = response.json()

        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")

        parts_out = candidates[0].get("content", {}).get("parts", [])
        if not parts_out:
            raise RuntimeError("Gemini returned empty response")

        result = parts_out[0].get("text", "").strip()
        if not result:
            raise RuntimeError("Gemini returned empty text")

        logger.info(
            "Prompt rewritten: '%s' -> '%s'",
            prompt[:60],
            result[:60],
        )
        return result

    async def check_status(self) -> bool:
        """Check whether the Gemini API is reachable and authenticated.

        Respects the circuit breaker — returns a cached False immediately
        when the circuit is open instead of hitting the API.

        Returns:
            True if the provider is operational, False otherwise.
        """
        if self._rate_limiter.is_backing_off:
            logger.debug(
                "Gemini script health check skipped — %s",
                "circuit OPEN" if self._rate_limiter.circuit_open
                else "rate limiter backing off",
            )
            return False

        try:
            client = self._get_client()
            url = f"/models/{self._model}"
            response = await client.get(url)
            if response.status_code == 200:
                self._rate_limiter.record_success()
                return True
            # 4xx/5xx on the model endpoint — record as error
            logger.warning(
                "Gemini script health check returned %d", response.status_code
            )
            self._rate_limiter.record_error()
            return False
        except Exception as exc:
            logger.warning("Gemini script health check failed: %s", exc)
            self._rate_limiter.record_error()
            return False

    async def aclose(self) -> None:
        """Close the underlying HTTP client and release its pool."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
