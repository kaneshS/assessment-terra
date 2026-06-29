import logging
import threading
from typing import Any

from app.services.ai_provider import AIFailure, GenerationResult

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model_cache: dict[str, tuple[Any, Any]] = {}


class LocalLLMProvider:
    """HuggingFace transformers provider with lazy model loading."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def _load_model(self) -> tuple[Any, Any]:
        with _model_lock:
            if self.model_name in _model_cache:
                return _model_cache[self.model_name]

            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
            except ImportError as exc:
                raise ImportError(
                    'Local LLM requires transformers and torch. '
                    'Install with: pip install -e ".[local]"'
                ) from exc

            logger.info(
                "Loading local model %s (first request may download weights)",
                self.model_name,
            )

            tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, trust_remote_code=True
            )
            model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.float32,
                trust_remote_code=True,
            )
            model.eval()

            _model_cache[self.model_name] = (model, tokenizer)
            return model, tokenizer

    def generate(self, prompt: str, max_completion_tokens: int) -> GenerationResult:
        try:
            model, tokenizer = self._load_model()
        except Exception as exc:
            raise AIFailure(f"Failed to load model: {exc}") from exc

        try:
            import torch

            messages = [{"role": "user", "content": prompt}]
            if hasattr(tokenizer, "apply_chat_template"):
                input_text = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            else:
                input_text = prompt

            inputs = tokenizer(input_text, return_tensors="pt")
            input_ids = inputs["input_ids"]
            prompt_tokens = int(input_ids.shape[1])

            pad_token_id = tokenizer.pad_token_id
            if pad_token_id is None:
                pad_token_id = tokenizer.eos_token_id

            with torch.no_grad():
                output_ids = model.generate(
                    input_ids,
                    attention_mask=inputs.get("attention_mask"),
                    max_new_tokens=max_completion_tokens,
                    do_sample=False,
                    pad_token_id=pad_token_id,
                )

            new_token_ids = output_ids[0, prompt_tokens:]
            # Drop trailing EOS/pad so counts match decoded text length.
            stop_ids = {
                tid
                for tid in (tokenizer.eos_token_id, pad_token_id)
                if tid is not None
            }
            trimmed_ids = new_token_ids
            while trimmed_ids.numel() > 0 and int(trimmed_ids[-1]) in stop_ids:
                trimmed_ids = trimmed_ids[:-1]

            completion_tokens = int(trimmed_ids.shape[0])
            response_text = tokenizer.decode(
                trimmed_ids, skip_special_tokens=True
            ).strip()

            return GenerationResult(
                text=response_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            )
        except Exception as exc:
            raise AIFailure(f"Generation failed: {exc}") from exc
