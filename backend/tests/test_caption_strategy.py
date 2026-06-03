from services.caption_strategy import build_model_aware_prompt, get_caption_target_strategy


def test_sdxl_strategy_defaults_to_wd_tags():
    strategy = get_caption_target_strategy("sdxl")
    assert strategy.default_style == "wd_tags"
    assert strategy.recommended_tagger == "WD-EVA02-Large-Tagger-v3"


def test_character_mode_prompt_omits_immutable_traits():
    prompt = build_model_aware_prompt(
        style="natural",
        target_model="flux_1",
        character_mode=True,
        provider_prompt="Write a natural caption.",
    )
    assert "omit immutable identity traits" in prompt
    assert "Do not hedge" in prompt


def test_non_character_mode_prompt_excludes_immutable_trait_instruction():
    prompt = build_model_aware_prompt(
        style="natural",
        target_model="flux_1",
        character_mode=False,
        provider_prompt="Write a natural caption.",
    )
    assert "omit immutable identity traits" not in prompt


def test_wan_prompt_includes_motion_rule():
    prompt = build_model_aware_prompt(
        style="natural",
        target_model="wan_2_2",
        character_mode=False,
        provider_prompt="Write a natural caption.",
    )
    assert "motion-focused caption" in prompt
    assert "never describe identity traits" in prompt
