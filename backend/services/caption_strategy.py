"""Model-aware caption strategy helpers."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptionTargetStrategy:
    key: str
    default_style: str
    recommended_tagger: str
    export_format: str
    prompt_template: str


_DEFAULT_PROMPT = (
    "Write a concrete training caption with only verifiable visual facts. "
    "Do not hedge with phrases like 'appears to', 'likely', 'possibly', 'seems to', or 'probably'."
)

TARGET_MODEL_STRATEGIES: dict[str, CaptionTargetStrategy] = {
    "flux_1": CaptionTargetStrategy(
        key="flux_1",
        default_style="natural",
        recommended_tagger="JoyCaption",
        export_format="ai-toolkit",
        prompt_template=(
            "Write natural-language prose captions for Flux training. "
            "Use complete sentences and concrete visual details."
        ),
    ),
    "flux_2": CaptionTargetStrategy(
        key="flux_2",
        default_style="natural",
        recommended_tagger="JoyCaption",
        export_format="ai-toolkit",
        prompt_template=(
            "Write natural-language prose captions for Flux training. "
            "Use complete sentences and concrete visual details."
        ),
    ),
    "z_image": CaptionTargetStrategy(
        key="z_image",
        default_style="natural",
        recommended_tagger="JoyCaption",
        export_format="ai-toolkit",
        prompt_template=(
            "Write literal natural-language captions for Z-Image training. "
            "Describe only what is visible."
        ),
    ),
    "wan_2_2": CaptionTargetStrategy(
        key="wan_2_2",
        default_style="natural",
        recommended_tagger="Qwen2.5-VL-7B",
        export_format="musubi-tuner",
        prompt_template=(
            "Write a motion-focused caption for WAN 2.2 video training. "
            "Describe action and setting; never describe identity traits."
        ),
    ),
    "sdxl": CaptionTargetStrategy(
        key="sdxl",
        default_style="wd_tags",
        recommended_tagger="WD-EVA02-Large-Tagger-v3",
        export_format="kohya_ss",
        prompt_template=(
            "Output comma-separated booru tags only for SDXL training. "
            "No prose sentences."
        ),
    ),
    "pony": CaptionTargetStrategy(
        key="pony",
        default_style="wd_tags",
        recommended_tagger="WD-EVA02-Large-Tagger-v3",
        export_format="kohya_ss",
        prompt_template=(
            "Output comma-separated booru tags only for Pony training. "
            "No prose sentences."
        ),
    ),
}

DEFAULT_TARGET_MODEL = "flux_1"


def get_caption_target_strategy(target_model: str | None) -> CaptionTargetStrategy:
    key = (target_model or DEFAULT_TARGET_MODEL).strip().lower()
    return TARGET_MODEL_STRATEGIES.get(key, TARGET_MODEL_STRATEGIES[DEFAULT_TARGET_MODEL])


def build_model_aware_prompt(
    style: str,
    target_model: str | None,
    character_mode: bool,
    provider_prompt: str,
) -> str:
    strategy = get_caption_target_strategy(target_model)
    parts = [strategy.prompt_template, provider_prompt, _DEFAULT_PROMPT]
    if character_mode:
        parts.append(
            "Character mode: omit immutable identity traits (face shape, eye color, permanent features, "
            "natural hair color if consistent, and signature clothing). "
            "Include only controllable attributes such as pose, expression, variable outfit, setting, lighting, "
            "camera angle, and props."
        )
    if style in {"danbooru_tags", "wd_tags"}:
        parts.append("Return only comma-separated tags.")
    return " ".join(parts)
