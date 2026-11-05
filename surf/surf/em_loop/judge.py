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

# Judge sampling defaults.
#
# Temperature is a parameter, not a constant: judge.py used to set 1.0 on every
# judge for a constraint that only binds Anthropic extended thinking, which
# ModelResource already enforces inside call_with_thinking. A non-thinking judge
# never needed the pin, and nothing could change it.
#
# The default stays 1.0 because lowering it was MEASURED TO BE MUCH WORSE for the
# pilot judge, not because the pin was right. At 1.0, MiMo-V2.6-Flash lost 7.4% of
# the 2026-11-05 phase B rows to verdicts that never emitted a <score>. At 0.2 it
# lost 85.1% over 175 calls: degenerate from the first token, not truncated, and
# well inside any cap. See results/phaseB_rejudge_t02/FINDING.md and decision
# 2026-11-05-B. This model appears to have no usable low-temperature regime.
#
# So do not lower this for MiMo without measuring first, and never set 0: the
# intra-rater pass in run_rater.py resamples at the production temperature and is
# vacuous at 0, and the retry below can only escape a bad draw if the next draw is
# allowed to differ. A judge whose own failures are correlated with the target
# needs the retry, which is the mitigation that actually survived measurement.
DEFAULT_JUDGE_TEMPERATURE = 1.0

# Response cap for a non-thinking judge. 2048 is the value every run so far used.
#
# Note the output order the score prompts ask for: <violated>, then <evidence>,
# then <score>, then <reasoning>. <evidence> quotes spans from the response and is
# NOT length-bounded, so it sits before the score and a tight cap CAN truncate
# before the score is emitted. An earlier version of this comment claimed the
# opposite and justified capping at 1024 on it. Scored output has run to 2196
# characters (median 471), so 1024 is not obviously safe, and the collapse it was
# meant to catch turned out not to be length-related at all.
DEFAULT_JUDGE_MAX_TOKENS = 2048

# Retries exist for a judge that returned no parseable score, and are the one
# mitigation here that measurement supports. Bounded at three, so an unlucky draw
# is recoverable without letting a genuinely unscoreable pair bill without limit.
# Useless at temperature 0, where every retry redraws the same text. Set 1 when
# MEASURING a judge's failure rate, since best-of-three hides it.
DEFAULT_JUDGE_ATTEMPTS = 3


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
        temperature: float = DEFAULT_JUDGE_TEMPERATURE,
        max_tokens: Optional[int] = None,
        max_attempts: int = DEFAULT_JUDGE_ATTEMPTS,
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
            temperature: Judge sampling temperature. Ignored when extended
                thinking is on, which requires 1.0. Keep it identical across
                judges being compared -- it is part of the instrument.
            max_tokens: Response cap for the judge. None means
                DEFAULT_JUDGE_MAX_TOKENS, or 16384 when thinking is on, where
                the budget has to cover the thinking block too.
            max_attempts: How many times to ask before recording an unscored
                verdict. 1 disables retrying.
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

        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
        self.max_attempts = max_attempts

        # Extended thinking requires temperature=1, and ModelResource forces it
        # inside the thinking path. Mirror that decision here instead of storing
        # what the caller asked for, so `config` reports the temperature that was
        # actually sent rather than one that was silently overridden.
        self.temperature = 1.0 if self.use_thinking else temperature

        # Extended thinking is gated on the provider string, and it also doubles
        # as the max_tokens switch below. Routing the same Claude model through
        # openrouter: therefore produces a different judge from anthropic:, which
        # matters whenever two judges are being compared.
        if max_tokens is None:
            max_tokens = 16384 if self.use_thinking else DEFAULT_JUDGE_MAX_TOKENS
        self.max_tokens = max_tokens

        self.model_resource = ModelResource.from_string(
            model,
            max_concurrency=max_concurrency,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

    @property
    def config(self) -> Dict[str, Any]:
        """Judge settings that belong in a record, so a run is reproducible."""
        return {
            "judge_model": f"{self.model_resource.provider}:{self.model_resource.model}",
            "judge_temperature": self.model_resource.query_params.temperature,
            "judge_thinking": self.use_thinking,
            "judge_thinking_budget": self.thinking_budget if self.use_thinking else None,
            "judge_max_tokens": self.max_tokens,
            "judge_max_attempts": self.max_attempts,
            "score_prompt": self.score_prompt_name,
            "n_assertions": self.n_assertions,
        }

    async def _judge_once(self, prompt: str) -> Verdict:
        """
        One judge call and its parse.

        A provider error becomes a not-ok Verdict rather than an exception, so a
        single bad call can never abort a batch.
        """
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

    async def judge(self, query: str, response: str) -> Verdict:
        """
        Score one query/response pair, re-asking a verdict that did not parse.

        Returns a Verdict. `verdict.ok` is False when the score did not parse, or
        the call failed, on every attempt; callers must drop those rather than
        treating them as 0. Attribution parse problems never make a verdict
        not-ok, they only add entries to `verdict.parse_warnings`.

        Retrying is not a cosmetic tidy-up. Judge failures are not independent of
        the target: on the 2026-11-05 phase B run the collapse rate ran 10, 14 and
        24 of 217 across the three arms, so dropping the failures moved each arm's
        mean by a different amount. `verdict.attempts` records what the record
        cost and the warnings name the discarded failures, so a run that only held
        together on retries cannot read as a clean one.
        """
        prompt = render_jinja(
            self.score_prompt_template,
            principle_specific_details=self.principle_specific_details,
            query=query,
            response=response,
        )

        discarded: List[str] = []
        for attempt in range(1, self.max_attempts + 1):
            verdict = await self._judge_once(prompt)
            verdict.attempts = attempt
            if verdict.ok:
                if discarded:
                    verdict.parse_warnings = [
                        *verdict.parse_warnings,
                        f"recovered_after:{';'.join(discarded)}",
                    ]
                return verdict
            # Truncated: a provider error can carry a whole response body, and
            # this goes into every record.
            discarded.append((verdict.error or "unknown")[:60])

        verdict.parse_warnings = [
            *verdict.parse_warnings,
            f"exhausted_attempts:{';'.join(discarded)}",
        ]
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
