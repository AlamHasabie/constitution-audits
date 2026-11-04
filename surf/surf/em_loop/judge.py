"""Single judge system for the EM loop.

Shared by the search loop and the pooled re-score. Both call `judge()` and get a
`Verdict`, so a record written by either carries the same fields.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from surf.core.models import ModelResource
from surf.core.utils import render_jinja, tqdm_gather
from surf.em_loop.prompts import DEFAULT_SCORE_PROMPT, SCORE_PROMPTS
from surf.em_loop.verdict import Verdict, parse_verdict


class SingleJudgeSystem:
    """
    Single Claude judge for scoring query/response pairs.

    Uses Opus 4.5 by default for high-quality violation scoring.
    """

    def __init__(
        self,
        principle_specific_details: str,
        model: str = "anthropic:claude-opus-4-5-20251101",
        max_concurrency: int = 20,
        use_thinking: bool = True,
        thinking_budget: int = 10000,
        score_prompt: Optional[str] = None,
        n_assertions: Optional[int] = None,
    ):
        """
        Initialize the judge.

        Args:
            principle_specific_details: The principle and scoring guidelines
            model: Model to use for judging
            max_concurrency: Maximum concurrent API calls
            use_thinking: Whether to use extended thinking (Anthropic only)
            thinking_budget: Token budget for extended thinking
            score_prompt: Name of a prompt in prompts.SCORE_PROMPTS. Defaults to
                the original prompt, so rubrics that do not ask for a different
                one are scored exactly as before.
            n_assertions: The rubric's declared assertion count. It bounds the
                judge's attribution output and switches attribution parsing on;
                None means this is not an attribution rubric.
        """
        self.principle_specific_details = principle_specific_details
        self.use_thinking = use_thinking and model.startswith("anthropic:")
        self.thinking_budget = thinking_budget

        self.score_prompt_name = score_prompt or DEFAULT_SCORE_PROMPT
        if self.score_prompt_name not in SCORE_PROMPTS:
            raise ValueError(
                f"unknown score_prompt {self.score_prompt_name!r}; "
                f"available: {sorted(SCORE_PROMPTS)}"
            )
        self.score_prompt_template = SCORE_PROMPTS[self.score_prompt_name]

        # A prompt that asks for attributions needs the count to bound them.
        # Without this check such a rubric would score normally and record no
        # attributions at all, which looks like a judge that found nothing.
        if "<violated>" in self.score_prompt_template and n_assertions is None:
            raise ValueError(
                f"score_prompt {self.score_prompt_name!r} asks the judge to attribute "
                "violations, so the rubric must declare n_assertions"
            )
        self.n_assertions = n_assertions

        # Extended thinking is gated on the provider string, and it also doubles
        # as the max_tokens switch below. Routing the same Claude model through
        # openrouter: therefore produces a different judge from anthropic:, which
        # matters whenever two judges are being compared.
        self.model_resource = ModelResource.from_string(
            model,
            max_concurrency=max_concurrency,
            max_tokens=16384 if self.use_thinking else 2048,
            temperature=1.0,  # Extended thinking requires temperature=1
        )

    @property
    def config(self) -> Dict[str, Any]:
        """Judge settings that belong in a record, so a run is reproducible."""
        return {
            "judge_model": f"{self.model_resource.provider}:{self.model_resource.model}",
            "judge_temperature": self.model_resource.query_params.temperature,
            "judge_thinking": self.use_thinking,
            "judge_thinking_budget": self.thinking_budget if self.use_thinking else None,
            "score_prompt": self.score_prompt_name,
            "n_assertions": self.n_assertions,
        }

    async def judge(self, query: str, response: str) -> Verdict:
        """
        Score one query/response pair.

        Returns a Verdict. `verdict.ok` is False when the score did not parse or
        the call failed; callers must drop those rather than treating them as 0.
        Attribution parse problems never make a verdict not-ok, they only add
        entries to `verdict.parse_warnings`.
        """
        prompt = render_jinja(
            self.score_prompt_template,
            principle_specific_details=self.principle_specific_details,
            query=query,
            response=response,
        )

        try:
            if self.use_thinking:
                text, thinking = await self.model_resource.call_with_thinking(
                    prompt,
                    thinking_budget=self.thinking_budget,
                )
            else:
                text = await self.model_resource.call(prompt)
                thinking = None
        except Exception as e:  # noqa: BLE001 - any provider error must be recorded, not raised
            return Verdict(raw="", error=f"call_failed:{type(e).__name__}: {e}")

        verdict = parse_verdict(text or "", n_assertions=self.n_assertions)
        verdict.thinking = thinking
        return verdict

    async def judge_batch(
        self,
        queries: List[str],
        responses: List[str],
        quiet: bool = False,
        on_progress: callable = None,
        desc: str = "Scoring",
    ) -> List[Verdict]:
        """
        Score a batch of pairs, one Verdict per input pair, order preserved.

        An exception escaping a task becomes a not-ok Verdict rather than an
        Exception in the list, so callers cannot accidentally count a failure as
        a score.
        """
        tasks = [
            self.judge(query, response) for query, response in zip(queries, responses)
        ]

        results = await tqdm_gather(
            tasks, desc=desc, return_exceptions=True, disable=quiet, on_progress=on_progress
        )

        return [
            r
            if isinstance(r, Verdict)
            else Verdict(raw="", error=f"task_failed:{type(r).__name__}: {r}")
            for r in results
        ]

    async def score(
        self,
        query: str,
        response: str,
    ) -> Tuple[Optional[float], Dict[str, Any]]:
        """
        Score a query/response pair.

        Returns (score, metadata). The score is None when the judge call or the
        <score> parse failed -- previously this returned 0.0, which is inside the
        no-violation band and so flowed into buffers, distributions and model
        comparisons as if the judge had found nothing wrong.
        """
        verdict = await self.judge(query, response)
        metadata = verdict.as_record_fields()
        metadata.pop("score", None)
        if verdict.thinking:
            metadata["thinking"] = verdict.thinking
        return verdict.score, metadata

    async def score_batch(
        self,
        queries: list[str],
        responses: list[str],
        quiet: bool = False,
        on_progress: callable = None,
    ) -> list[Tuple[Optional[float], Dict[str, Any]]]:
        """
        Score a batch of query/response pairs.

        Returns one (score, metadata) tuple per input pair, in order. A score of
        None means the pair was not scored and must be excluded from statistics.
        """
        verdicts = await self.judge_batch(
            queries, responses, quiet=quiet, on_progress=on_progress
        )

        out: list[Tuple[Optional[float], Dict[str, Any]]] = []
        for verdict in verdicts:
            metadata = verdict.as_record_fields()
            metadata.pop("score", None)
            if verdict.thinking:
                metadata["thinking"] = verdict.thinking
            out.append((verdict.score, metadata))
        return out


def load_rubric(rubric_path: str) -> Dict[str, Any]:
    """
    Load a rubric YAML file.

    Args:
        rubric_path: Path to YAML file

    Returns:
        Dict with rubric configuration
    """
    import yaml

    # Explicit utf-8: the default encoding is locale-dependent, so on Windows
    # (cp1252) rubrics containing non-ASCII characters either mojibake or raise
    # UnicodeDecodeError. rubrics/rebuttal.yaml hits the latter.
    with open(rubric_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_principle_from_rubric(rubric: Dict[str, Any]) -> str:
    """
    Extract principle_specific_details from a rubric.

    Args:
        rubric: Loaded rubric dict

    Returns:
        The principle_specific_details string
    """
    return rubric.get("principle_specific_details", "")


def get_score_prompt_from_rubric(rubric: Dict[str, Any]) -> Optional[str]:
    """
    Extract the judge prompt name a rubric asks for, if any.

    None means the original prompt, which is what every rubric predating the
    banded variant gets.
    """
    return rubric.get("score_prompt")


def get_n_assertions_from_rubric(rubric: Dict[str, Any]) -> Optional[int]:
    """
    The assertion count a rubric declares, or None to fall back to counting.

    Declared counts are preferred: a rubric that also carries a numbered band
    list cannot be counted reliably.
    """
    value = rubric.get("n_assertions")
    return int(value) if value is not None else None
