from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .models import EventType, Evidence, ProtocolEvent
from .protocol_events import Paragraph


class StructuredBackend(Protocol):
    """Provider-independent interface for structured model generation."""

    def complete(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]: ...


class BatchStructuredBackend(StructuredBackend, Protocol):
    """Optional extension for backends that can process prompts in one model batch."""

    def complete_many(
        self,
        prompts: list[str],
        json_schema: dict[str, Any],
    ) -> list[dict[str, Any]]: ...


class StructuredOutputError(ValueError):
    """Raised when a model response is not one complete, strict JSON object."""


def _distribution_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _token_count(token_ids: Any) -> int | None:
    if token_ids is None:
        return None
    try:
        return len(token_ids)
    except TypeError:
        return None


def _strict_json_object(text: str, *, response_index: int) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in pairs:
            if key in parsed:
                raise ValueError(f"duplicate JSON key: {key}")
            parsed[key] = value
        return parsed

    try:
        payload = json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (TypeError, ValueError) as exc:
        raise StructuredOutputError(
            f"response {response_index} is not one strict JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise StructuredOutputError(f"response {response_index} is not a JSON object")
    return payload


class VLLMStructuredBackend:
    """Pinned, offline vLLM chat backend with JSON-schema-constrained batch decoding.

    vLLM is deliberately imported and the engine is constructed only when this class is
    instantiated. This keeps the core package importable on API and CPU nodes that do not have
    the Roihu inference environment installed.
    """

    SUPPORTED_VLLM_VERSION = "0.19.1"
    _PINNED_REVISION = re.compile(r"[0-9a-f]{40}", re.IGNORECASE)

    def __init__(
        self,
        *,
        model: str,
        revision: str,
        tokenizer_revision: str,
        max_tokens: int = 2_048,
        seed: int = 0,
        dtype: str = "bfloat16",
        max_model_len: int = 8_192,
        tensor_parallel_size: int = 1,
        gpu_memory_utilization: float = 0.85,
    ) -> None:
        for name, value in (
            ("model", model),
            ("revision", revision),
            ("tokenizer_revision", tokenizer_revision),
        ):
            if not value.strip():
                raise ValueError(f"{name} must be non-empty")
        for name, value in (("revision", revision), ("tokenizer_revision", tokenizer_revision)):
            if self._PINNED_REVISION.fullmatch(value.strip()) is None:
                raise ValueError(f"{name} must be a pinned 40-character Git commit")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if max_model_len < 1:
            raise ValueError("max_model_len must be positive")
        if tensor_parallel_size < 1:
            raise ValueError("tensor_parallel_size must be positive")
        if not 0 < gpu_memory_utilization <= 1:
            raise ValueError("gpu_memory_utilization must be in (0, 1]")

        # These imports must stay inside construction: vLLM is an HPC-only optional runtime.
        import vllm
        from vllm.sampling_params import StructuredOutputsParams

        installed_version = getattr(vllm, "__version__", None)
        if installed_version != self.SUPPORTED_VLLM_VERSION:
            raise RuntimeError(
                "VLLMStructuredBackend requires vLLM "
                f"{self.SUPPORTED_VLLM_VERSION}, found {installed_version!r}"
            )

        self.model = model
        self.revision = revision
        self.tokenizer_revision = tokenizer_revision
        self.max_tokens = max_tokens
        self.seed = seed
        self.dtype = dtype
        self.max_model_len = max_model_len
        self.tensor_parallel_size = tensor_parallel_size
        self.gpu_memory_utilization = gpu_memory_utilization
        self._runtime_versions = {
            "vllm": installed_version,
            "torch": _distribution_version("torch"),
            "transformers": _distribution_version("transformers"),
        }
        self._last_batch_metadata: list[dict[str, Any]] = []
        self._sampling_params_type = vllm.SamplingParams
        self._structured_outputs_type = StructuredOutputsParams
        self._llm = vllm.LLM(
            model=model,
            revision=revision,
            tokenizer_revision=tokenizer_revision,
            trust_remote_code=False,
            dtype=dtype,
            max_model_len=max_model_len,
            tensor_parallel_size=tensor_parallel_size,
            gpu_memory_utilization=gpu_memory_utilization,
            seed=seed,
        )

    def _chat_prompt_token_count(self, conversation: list[dict[str, str]]) -> int:
        """Count the exact chat-template input before reserving generation tokens."""

        tokenizer = self._llm.get_tokenizer()
        token_ids = tokenizer.apply_chat_template(
            conversation,
            tokenize=True,
            add_generation_prompt=True,
        )
        input_ids = getattr(token_ids, "input_ids", token_ids)
        try:
            return len(input_ids)
        except TypeError as error:
            raise RuntimeError("tokenizer did not return a countable chat prompt") from error

    @property
    def provenance(self) -> dict[str, Any]:
        """Return reproducibility metadata without credentials or environment contents."""

        return {
            "backend": "vllm_offline_chat",
            "runtime_versions": dict(self._runtime_versions),
            "model": self.model,
            "revision": self.revision,
            "tokenizer_revision": self.tokenizer_revision,
            "trust_remote_code": False,
            "engine": {
                "dtype": self.dtype,
                "max_model_len": self.max_model_len,
                "tensor_parallel_size": self.tensor_parallel_size,
                "gpu_memory_utilization": self.gpu_memory_utilization,
            },
            "sampling": {
                "temperature": 0.0,
                "seed": self.seed,
                "max_tokens": self.max_tokens,
                "n": 1,
            },
        }

    @property
    def last_batch_metadata(self) -> list[dict[str, Any]]:
        """Return token counts and finish states from the last batch, never prompt contents."""

        return [dict(item) for item in self._last_batch_metadata]

    def complete(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        return self.complete_many([prompt], json_schema)[0]

    def complete_many(
        self,
        prompts: list[str],
        json_schema: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self._last_batch_metadata = []
        if not prompts:
            return []
        if any(not isinstance(prompt, str) or not prompt.strip() for prompt in prompts):
            raise ValueError("every prompt must be a non-empty string")

        conversations = [[{"role": "user", "content": prompt}] for prompt in prompts]
        for index, conversation in enumerate(conversations):
            prompt_tokens = self._chat_prompt_token_count(conversation)
            if prompt_tokens + self.max_tokens > self.max_model_len:
                raise StructuredOutputError(
                    f"prompt {index} requires {prompt_tokens} input tokens plus "
                    f"{self.max_tokens} reserved output tokens, exceeding "
                    f"max_model_len={self.max_model_len}"
                )

        structured_outputs = self._structured_outputs_type(
            json=json_schema,
            disable_additional_properties=True,
        )
        sampling_params = self._sampling_params_type(
            temperature=0.0,
            seed=self.seed,
            max_tokens=self.max_tokens,
            n=1,
            structured_outputs=structured_outputs,
        )
        request_outputs = self._llm.chat(
            conversations,
            sampling_params=sampling_params,
            use_tqdm=False,
        )
        if len(request_outputs) != len(prompts):
            raise StructuredOutputError(
                f"vLLM returned {len(request_outputs)} responses for {len(prompts)} prompts"
            )

        batch_metadata: list[dict[str, Any]] = []
        for request_output in request_outputs:
            completions = getattr(request_output, "outputs", None)
            completion = completions[0] if isinstance(completions, list) and completions else None
            batch_metadata.append(
                {
                    "prompt_tokens": _token_count(
                        getattr(request_output, "prompt_token_ids", None)
                    ),
                    "completion_tokens": _token_count(
                        getattr(completion, "token_ids", None)
                    ),
                    "finish_reason": getattr(completion, "finish_reason", None),
                }
            )
        self._last_batch_metadata = batch_metadata

        parsed: list[dict[str, Any]] = []
        for index, request_output in enumerate(request_outputs):
            completions = getattr(request_output, "outputs", None)
            if not isinstance(completions, list) or len(completions) != 1:
                raise StructuredOutputError(
                    f"response {index} did not contain exactly one completion"
                )
            completion = completions[0]
            if getattr(completion, "finish_reason", None) != "stop":
                raise StructuredOutputError(f"response {index} did not finish cleanly")
            text = getattr(completion, "text", None)
            if not isinstance(text, str):
                raise StructuredOutputError(f"response {index} did not contain text")
            parsed.append(_strict_json_object(text, response_index=index))
        return parsed


class RawQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)


class RawCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1)
    value: int = Field(ge=1)


class LLMEventCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    paragraph_id: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    quote: str = Field(min_length=1)
    duration: RawQuantity | None = None
    temperature: RawQuantity | None = None
    pressure: RawQuantity | None = None
    timestep: RawQuantity | None = None
    ensemble: str | None = None
    restraints: str | None = None
    replicates: RawCount | None = None
    confidence: float = Field(ge=0, le=1)


class LLMEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[LLMEventCandidate]


class EvidenceIntegrityError(ValueError):
    """Raised when a proposed event is not exactly supported by supplied text."""


_QUANTITY = re.compile(
    r"\s*(?P<value>[+-]?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>fs|ps|ns|us|µs|μs|ms|K|kelvin|°C|Celsius|bar|atm)\s*",
    re.IGNORECASE,
)
_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_ALLOWED_ENSEMBLES = {"NVE", "NVT", "NPT", "NPAT", "NPH"}


def _canonical_unit(unit: str) -> str:
    compact = unit.strip().replace("μ", "µ")
    aliases = {"kelvin": "K", "celsius": "°C", "c": "°C"}
    return aliases.get(compact.casefold(), compact)


def _verify_quantity(quantity: RawQuantity, quote: str) -> tuple[float, str]:
    if quantity.raw_text not in quote:
        raise EvidenceIntegrityError("quantity raw_text is not present in the evidence quote")
    match = _QUANTITY.fullmatch(quantity.raw_text)
    if match is None:
        raise EvidenceIntegrityError("quantity raw_text does not match the accepted numeric-unit form")
    parsed_value = float(match.group("value"))
    parsed_unit = _canonical_unit(match.group("unit"))
    supplied_unit = _canonical_unit(quantity.unit)
    if not math.isclose(parsed_value, quantity.value, rel_tol=0.0, abs_tol=1e-12):
        raise EvidenceIntegrityError("quantity value disagrees with raw_text")
    if parsed_unit.casefold() != supplied_unit.casefold():
        raise EvidenceIntegrityError("quantity unit disagrees with raw_text")
    return parsed_value, parsed_unit


def _duration_ps(quantity: RawQuantity, quote: str) -> float:
    value, unit = _verify_quantity(quantity, quote)
    factor = {"fs": 1e-3, "ps": 1.0, "ns": 1e3, "us": 1e6, "µs": 1e6, "ms": 1e9}.get(
        unit.casefold().replace("μ", "µ")
    )
    if factor is None:
        raise EvidenceIntegrityError("unsupported duration unit")
    return value * factor


def _temperature_k(quantity: RawQuantity, quote: str) -> float:
    value, unit = _verify_quantity(quantity, quote)
    if unit.casefold() == "k":
        return value
    if unit == "°C":
        return value + 273.15
    raise EvidenceIntegrityError("unsupported temperature unit")


def _pressure_bar(quantity: RawQuantity, quote: str) -> float:
    value, unit = _verify_quantity(quantity, quote)
    if unit.casefold() == "bar":
        return value
    if unit.casefold() == "atm":
        return value * 1.01325
    raise EvidenceIntegrityError("unsupported pressure unit")


def _timestep_fs(quantity: RawQuantity, quote: str) -> float:
    value, unit = _verify_quantity(quantity, quote)
    if unit.casefold() == "fs":
        return value
    if unit.casefold() == "ps":
        return value * 1000
    raise EvidenceIntegrityError("unsupported timestep unit")


def _replicate_count(count: RawCount, quote: str) -> int:
    if count.raw_text not in quote:
        raise EvidenceIntegrityError("replicate raw_text is not present in the evidence quote")
    token = count.raw_text.strip().casefold()
    parsed = int(token) if token.isdigit() else _COUNT_WORDS.get(token)
    if parsed is None:
        raise EvidenceIntegrityError("replicate raw_text is not an accepted count")
    if parsed != count.value:
        raise EvidenceIntegrityError("replicate value disagrees with raw_text")
    return parsed


class SchemaConstrainedEventExtractor:
    """Accept only model events that pass exact evidence and deterministic unit checks."""

    def __init__(self, backend: StructuredBackend, model_id: str) -> None:
        self.backend = backend
        self.model_id = model_id

    @staticmethod
    def build_prompt(paragraphs: list[Paragraph]) -> str:
        blocks = "\n\n".join(
            f"[paragraph_id={paragraph.paragraph_id}; section={paragraph.section}]\n{paragraph.text}"
            for paragraph in paragraphs
        )
        return (
            "Extract only explicitly stated molecular-dynamics protocol events. "
            "Do not infer missing values and do not use outside knowledge. "
            "For each event, copy one exact evidence quote from one supplied paragraph and provide "
            "zero-based character offsets relative to that paragraph. For every numeric field, "
            "copy the exact numeric-unit expression into raw_text and also return its parsed value "
            "and unit. Return an empty events list when no supported event is present.\n\n"
            f"SOURCE PARAGRAPHS\n{blocks}"
        )

    @staticmethod
    def _prompt(paragraphs: list[Paragraph]) -> str:
        """Backward-compatible alias for callers that used the original private helper."""

        return SchemaConstrainedEventExtractor.build_prompt(paragraphs)

    def validate_response(
        self,
        paragraphs: list[Paragraph],
        response: dict[str, Any],
    ) -> list[ProtocolEvent]:
        """Validate one decoded response against its exact source paragraphs."""

        parsed = LLMEventResponse.model_validate(response)
        by_id = {paragraph.paragraph_id: paragraph for paragraph in paragraphs}
        events: list[ProtocolEvent] = []
        seen: set[str] = set()

        for candidate in parsed.events:
            paragraph = by_id.get(candidate.paragraph_id)
            if paragraph is None:
                raise EvidenceIntegrityError(f"unknown paragraph_id: {candidate.paragraph_id}")
            if candidate.end_char > len(paragraph.text):
                raise EvidenceIntegrityError("evidence range exceeds paragraph length")
            if paragraph.text[candidate.start_char : candidate.end_char] != candidate.quote:
                raise EvidenceIntegrityError("evidence quote does not match source offsets")

            attributes_present = any(
                value is not None
                for value in (
                    candidate.duration,
                    candidate.temperature,
                    candidate.pressure,
                    candidate.timestep,
                    candidate.ensemble,
                    candidate.restraints,
                    candidate.replicates,
                )
            )
            if not attributes_present:
                raise EvidenceIntegrityError("event has no protocol attribute")

            ensemble = candidate.ensemble.upper() if candidate.ensemble is not None else None
            if ensemble is not None:
                if candidate.ensemble not in candidate.quote:
                    raise EvidenceIntegrityError("ensemble text is not present in the evidence quote")
                if ensemble not in _ALLOWED_ENSEMBLES:
                    raise EvidenceIntegrityError("unsupported ensemble")
            if candidate.restraints is not None and candidate.restraints not in candidate.quote:
                raise EvidenceIntegrityError("restraints text is not present in the evidence quote")

            normalized = {
                "duration_ps": _duration_ps(candidate.duration, candidate.quote)
                if candidate.duration is not None
                else None,
                "temperature_k": _temperature_k(candidate.temperature, candidate.quote)
                if candidate.temperature is not None
                else None,
                "pressure_bar": _pressure_bar(candidate.pressure, candidate.quote)
                if candidate.pressure is not None
                else None,
                "timestep_fs": _timestep_fs(candidate.timestep, candidate.quote)
                if candidate.timestep is not None
                else None,
                "replicates": _replicate_count(candidate.replicates, candidate.quote)
                if candidate.replicates is not None
                else None,
            }
            stable_payload = "|".join(
                [
                    paragraph.document_id,
                    paragraph.paragraph_id,
                    str(candidate.start_char),
                    str(candidate.end_char),
                    candidate.event_type.value,
                    repr(sorted(normalized.items())),
                    ensemble or "",
                    candidate.restraints or "",
                ]
            )
            event_id = f"llm-event-{hashlib.sha256(stable_payload.encode('utf-8')).hexdigest()[:16]}"
            if event_id in seen:
                continue
            seen.add(event_id)
            evidence = Evidence(
                document_id=paragraph.document_id,
                section=paragraph.section,
                paragraph_id=paragraph.paragraph_id,
                quote=candidate.quote,
                start_char=candidate.start_char,
                end_char=candidate.end_char,
                context_sha256=hashlib.sha256(paragraph.text.encode("utf-8")).hexdigest(),
            )
            events.append(
                ProtocolEvent(
                    event_id=event_id,
                    event_type=candidate.event_type,
                    duration_ps=normalized["duration_ps"],
                    temperature_k=normalized["temperature_k"],
                    pressure_bar=normalized["pressure_bar"],
                    timestep_fs=normalized["timestep_fs"],
                    ensemble=ensemble,
                    restraints=candidate.restraints,
                    replicates=normalized["replicates"],
                    evidence=[evidence],
                    relation_method=f"schema_constrained_llm:{self.model_id}:exact_span_v1",
                    confidence=candidate.confidence,
                )
            )
        return events

    def extract(self, paragraphs: list[Paragraph]) -> list[ProtocolEvent]:
        response = self.backend.complete(
            self.build_prompt(paragraphs),
            LLMEventResponse.model_json_schema(),
        )
        return self.validate_response(paragraphs, response)

    def extract_many(
        self,
        paragraph_batches: list[list[Paragraph]],
    ) -> list[list[ProtocolEvent]]:
        """Extract independent documents with one backend batch when supported."""

        if not paragraph_batches:
            return []
        prompts = [self.build_prompt(paragraphs) for paragraphs in paragraph_batches]
        schema = LLMEventResponse.model_json_schema()
        complete_many = getattr(self.backend, "complete_many", None)
        if callable(complete_many):
            responses = complete_many(prompts, schema)
        else:
            responses = [self.backend.complete(prompt, schema) for prompt in prompts]
        if len(responses) != len(paragraph_batches):
            raise StructuredOutputError(
                f"backend returned {len(responses)} responses for {len(paragraph_batches)} batches"
            )
        return [
            self.validate_response(paragraphs, response)
            for paragraphs, response in zip(paragraph_batches, responses, strict=True)
        ]
