import json
import os
import time


def with_retries(fn, attempts: int = 3, base_delay: float = 2.0,
                 sleep=time.sleep):
    for attempt in range(attempts):
        try:
            return fn()
        except Exception:
            if attempt == attempts - 1:
                raise
            sleep(base_delay * (2 ** attempt))


REQUEST_TIMEOUT_MS = 120_000  # a hung socket must fail so with_retries can act


class GeminiClient:
    def __init__(self, extract_model: str, embed_model: str):
        from google import genai
        self.client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options={"timeout": REQUEST_TIMEOUT_MS})
        self.extract_model = extract_model
        self.embed_model = embed_model
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def _tally(self, resp) -> None:
        self.usage["calls"] += 1
        um = getattr(resp, "usage_metadata", None)
        if um is not None:
            self.usage["input_tokens"] += um.prompt_token_count or 0
            self.usage["output_tokens"] += um.candidates_token_count or 0

    def generate_json(self, prompt: str):
        def call():
            resp = self.client.models.generate_content(
                model=self.extract_model,
                contents=prompt,
                config={"response_mime_type": "application/json",
                        # thinking tokens bill as output; classification
                        # doesn't need them
                        "thinking_config": {"thinking_level": "low"}},
            )
            self._tally(resp)
            return json.loads(resp.text)
        return with_retries(call)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):
            chunk = texts[i:i + 100]

            def call():
                resp = self.client.models.embed_content(
                    model=self.embed_model, contents=chunk)
                self.usage["calls"] += 1
                return [e.values for e in resp.embeddings]

            # each text counts against a 3000/min quota; pace to ~2400/min
            # and back off past the quota window on 429s
            out.extend(with_retries(call, base_delay=20.0))
            if i + 100 < len(texts):
                time.sleep(2.5)
        return out
