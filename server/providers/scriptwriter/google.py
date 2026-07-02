"""Google Gemini scriptwriter provider with rate limiting and retry."""

import logging
import json
import re
from typing import Optional

import httpx

from server.providers.base import ScriptWriterProvider
from server.utils.rate_limiter import RateLimiter, retry_with_backoff

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

    if truncated:
        # The LLM was cut off — remove the last (likely incomplete) sentence.
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
                headers={"Content-Type": "application/json"},
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

    async def write_talk_segment(self, context: dict) -> dict:
        """Generate a talk show segment script from structured show context.

        Args:
            context: Talk show context with topic, speakers, style, continuity,
                and target duration.

        Returns:
            A dict with script_text, speakers, estimated_duration, and metadata.
        """
        return await retry_with_backoff(
            self._write_talk_segment_impl,
            context,
            max_retries=2,
            base_delay=5.0,
            max_delay=30.0,
            rate_limiter=self._rate_limiter,
            operation_name="gemini_write_talk_segment",
        )

    async def _write_talk_segment_impl(self, context: dict) -> dict:
        """Internal write_talk_segment implementation."""
        client = self._get_client()

        segment_type = context.get("segment_type", "conversation")
        topic = context.get("topic", {})
        speakers = context.get("speakers", [])
        speaker_names = [
            str(s.get("name", "")).strip()
            for s in speakers
            if str(s.get("name", "")).strip()
        ] or ["Host"]
        target_duration = int(context.get("target_duration", 120) or 120)
        target_words = max(60, int((target_duration / 60) * 150))

        if segment_type == "monologue":
            output_rule = (
                "Return ONLY plain spoken words for one host. No markdown, "
                "stage directions, speaker labels, or formatting."
            )
        else:
            output_rule = (
                "Return ONLY a valid JSON array. Each item must be an object "
                'with "speaker", "text", and optional "pace" fields. '
                f"Use speaker names exactly from this list: {', '.join(speaker_names)}. "
                'Allowed pace values are "quick", "normal", and "slow". '
                "Do not wrap the JSON in markdown or add explanation."
            )

        system_prompt = f"""You write prerecorded AI radio talk-show segments.

Show: {context.get("show_name", "AI Radio Talk")}
Segment type: {segment_type}
Target length: about {target_words} spoken words.

Rules:
- Make it sound like real radio: specific, conversational, and listenable.
- Keep turns short enough for text-to-speech, usually one or two sentences.
- Avoid fake caller references, fake live facts, citations, and unverifiable claims.
- Do not use markdown, parenthetical stage directions, sound effects, or bracketed cues.
- Every spoken sentence must be complete.
- Follow the configured host and co-host personalities.
- {output_rule}"""

        speaker_lines = []
        for speaker in speakers:
            name = speaker.get("name", "Host")
            personality = speaker.get("personality_prompt", "")
            if personality:
                speaker_lines.append(f"- {name}: {personality}")
            else:
                speaker_lines.append(f"- {name}")

        previous_segments = context.get("previous_segments", [])
        previous_lines = [
            f"- {s.get('title', 'Previous segment')}: {s.get('summary', '')}"
            for s in previous_segments
            if s.get("summary")
        ]

        user_parts = [
            f"Topic title: {topic.get('title', 'Untitled topic')}",
            f"Topic prompt: {topic.get('prompt', '')}",
        ]
        if topic.get("notes"):
            user_parts.append(f"Topic notes: {topic.get('notes')}")
        if speaker_lines:
            user_parts.append("Speakers:\n" + "\n".join(speaker_lines))
        if context.get("conversation_style"):
            user_parts.append(f"Conversation style: {context.get('conversation_style')}")
        if context.get("intro_style"):
            user_parts.append(f"Intro style: {context.get('intro_style')}")
        if context.get("outro_style"):
            user_parts.append(f"Outro style: {context.get('outro_style')}")
        if previous_lines:
            user_parts.append("Recent segment context:\n" + "\n".join(previous_lines))
        if context.get("current_time"):
            user_parts.append(f"Station local time: {context.get('current_time')}")

        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "\n\n".join(user_parts)}],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": min(4096, max(1024, target_words * 8)),
                "temperature": 0.85,
            },
        }

        try:
            logger.info("Generating %s talk segment via Gemini", segment_type)
            url = f"/models/{self._model}:generateContent?key={self._api_key}"
            response = await client.post(url, json=payload)

            if response.status_code == 429:
                logger.warning("Gemini rate limited")
                self._rate_limiter.record_error()
                raise RuntimeError("Gemini rate limited")

            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("Gemini returned no candidates")

            parts_out = candidates[0].get("content", {}).get("parts", [])
            if not parts_out:
                raise RuntimeError("Gemini returned empty response")

            raw_text = parts_out[0].get("text", "").strip()
            if not raw_text:
                raise RuntimeError("Gemini returned empty text")

            if segment_type == "monologue":
                script_text = _clean_for_tts(
                    raw_text,
                    truncated=candidates[0].get("finishReason") == "MAX_TOKENS",
                )
                used_speakers = [speaker_names[0]]
                word_count = len(script_text.split())
            else:
                script_text, used_speakers, word_count = self._normalize_talk_json(
                    raw_text,
                    allowed_speakers=speaker_names,
                )

            if not script_text:
                raise RuntimeError("Gemini talk segment was empty after cleaning")

            estimated_duration = (word_count / 150) * 60
            return {
                "script_text": script_text,
                "segment_type": segment_type,
                "speakers": used_speakers,
                "estimated_duration": estimated_duration,
                "word_count": word_count,
                "context": context,
                "model": self._model,
            }

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.error("Gemini talk API error: %s %s", status, exc.response.text[:200])
            raise RuntimeError(f"Gemini API error: {status}") from exc
        except httpx.RequestError as exc:
            logger.error("Gemini talk request failed: %s", exc)
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

    @staticmethod
    def _normalize_talk_json(
        raw_text: str, allowed_speakers: list[str]
    ) -> tuple[str, list[str], int]:
        """Validate and normalize Gemini's multi-speaker JSON output."""
        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()

        try:
            lines = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Gemini returned invalid talk segment JSON") from exc

        if not isinstance(lines, list) or not lines:
            raise RuntimeError("Gemini returned empty talk segment JSON")

        allowed = set(allowed_speakers)
        fallback = allowed_speakers[0] if allowed_speakers else "Host"
        normalized = []
        used_speakers: list[str] = []
        word_count = 0

        for line in lines:
            if not isinstance(line, dict):
                continue
            speaker = str(line.get("speaker", fallback)).strip() or fallback
            if speaker not in allowed:
                speaker = fallback
            text_value = _clean_for_tts(str(line.get("text", "")))
            if not text_value:
                continue
            pace = str(line.get("pace", "normal")).strip().lower()
            if pace not in {"quick", "normal", "slow"}:
                pace = "normal"

            normalized.append({"speaker": speaker, "text": text_value, "pace": pace})
            if speaker not in used_speakers:
                used_speakers.append(speaker)
            word_count += len(text_value.split())

        if not normalized:
            raise RuntimeError("Gemini returned no usable talk lines")

        return json.dumps(normalized), used_speakers, word_count

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
            url = f"/models/{self._model}:generateContent?key={self._api_key}"
            response = await client.post(url, json=payload)

            if response.status_code == 429:
                logger.warning("Gemini rate limited")
                self._rate_limiter.record_error()
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

        url = f"/models/{self._model}:generateContent?key={self._api_key}"
        response = await client.post(url, json=payload)

        if response.status_code == 429:
            self._rate_limiter.record_error()
            raise RuntimeError("Gemini rate limited")

        response.raise_for_status()
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
            url = f"/models/{self._model}?key={self._api_key}"
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
