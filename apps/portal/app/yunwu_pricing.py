"""Yunwu pricing rules extracted from the public pricing frontend bundle.

The pricing payload only provides base fields such as quota_type, model_price,
model_ratio and completion_ratio. The Yunwu pricing page applies additional
frontend multipliers for several fixed-price multimedia models. This module
replays those deterministic rules server-side so the public pricing API and UI
match the upstream site more closely without exposing upstream hosts or auth.
"""
from __future__ import annotations

from typing import NamedTuple


class BillingProfile(NamedTuple):
    label: str
    unit: str


YUNWU_QUOTA1_MULTIPLIERS: dict[str, float] = {
    "aigc-image": 20.0,
    "aigc-video": 23.0,
    "aigc-image-gem": 30.0,
    "aigc-image-qwen": 30.0,
    "aigc-image-hunyuan": 20.0,
    "aigc-video-vidu": 25.0,
    "aigc-template-effect-vidu": 40.0,
    "aigc-video-kling": 30.0,
    "aigc-video-hailuo": 23.0,
    "kling-image": 2.5,
    "kling-omni-image": 20.0,
    "kling-video": 100.0,
    "kling-omni-video": 100.0,
    "kling-avatar-image2video": 100.0,
    "kling-audio": 5.0,
    "kling-custom-voices": 5.0,
    "kling-effects": 200.0,
    "kling-multi-elements": 100.0,
    "kling-video-extend": 100.0,
    "kling-advanced-lip-sync": 50.0,
    "kling-image-recognize": 10.0,
    "viduq2": 18.75,
    "viduq1": 62.5,
    "viduq2-turbo": 18.75,
    "viduq2-pro": 25.0,
    "viduq3-pro": 218.75,
    "viduq3-turbo": 125.0,
    "viduq3": 156.25,
    "viduq3-mix": 390.625,
    "viduq1-classic": 250.0,
    "vidu2.0": 62.5,
    "audio1.0": 31.25,
    "vidu-tts": 31.25,
    "MiniMax-Hailuo-02": 200.0,
    "MiniMax-Hailuo-2.3": 200.0,
    "MiniMax-Hailuo-2.3-Fast": 135.0,
    "S2V-01": 200.0,
    "MiniMax-Voice-Clone": 990.0,
    "MiniMax-Voice-Design": 200.0,
    "speech-02-hd": 350.0,
    "speech-02-turbo": 200.0,
    "speech-2.6-hd": 350.0,
    "speech-2.6-turbo": 200.0,
    "speech-2.8-hd": 350.0,
    "speech-2.8-turbo": 200.0,
}

YUNWU_QUOTA4_MULTIPLIERS: dict[str, float] = {
    "kling-motion-control": 50.0,
    "doubao-seedance-2-0": 25.0,
}

YUNWU_IMAGE_MODELS: set[str] = {
    "aigc-image",
    "aigc-image-gem",
    "aigc-image-qwen",
    "aigc-image-hunyuan",
    "kling-image",
    "kling-omni-image",
    "doubao-seedream-4-0-250828",
    "doubao-seedream-4-5-251128",
    "bytedance/seedream-4",
    "black-forest-labs/flux-fill-dev",
    "fal-ai/qwen-image-edit-lora",
    "fal-ai/qwen-image-edit-plus",
    "fal-ai/imagen4/preview",
    "fal-ai/bytedance/seedream/v4/edit",
    "fal-ai/bytedance/seedream/v4/text-to-image",
    "fal-ai/flux-pro/kontext/max/multi",
    "fal-ai/flux-pro/kontext/max",
    "fal-ai/flux-pro/kontext/text-to-image",
    "fal-ai/flux-pro/kontext",
    "fal-ai/flux-1/schnell/redux",
    "fal-ai/flux-1/dev/redux",
    "fal-ai/flux-1/dev/image-to-image",
    "fal-ai/flux-1/dev",
    "fal-ai/nano-banana",
    "fal-ai/nano-banana/edit",
    "lucataco/flux-schnell-lora",
    "lucataco/flux-dev-lora",
    "stability-ai/stable-diffusion",
    "stability-ai/sdxl",
    "stability-ai/stable-diffusion-inpainting",
    "stability-ai/stable-diffusion-img2img",
}

YUNWU_VIDEO_MODELS: set[str] = {
    "aigc-video",
    "aigc-video-vidu",
    "aigc-template-effect-vidu",
    "aigc-video-kling",
    "aigc-video-hailuo",
    "grok-imagine-video",
    "kling-video",
    "kling-omni-video",
    "kling-avatar-image2video",
    "kling-video-extend",
    "viduq2",
    "viduq1",
    "viduq2-turbo",
    "viduq2-pro",
    "viduq3-pro",
    "viduq3-turbo",
    "viduq3",
    "viduq3-mix",
    "viduq1-classic",
    "vidu2.0",
}

YUNWU_AUDIO_MODELS: set[str] = {
    "audio1.0",
    "vidu-tts",
    "MiniMax-Hailuo-02",
    "MiniMax-Hailuo-2.3",
    "MiniMax-Hailuo-2.3-Fast",
    "S2V-01",
    "MiniMax-Voice-Clone",
    "MiniMax-Voice-Design",
    "speech-01",
    "speech-01-hd",
    "speech-01-turbo",
    "speech-02",
    "speech-02-hd",
    "speech-02-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
    "speech-2.8-hd",
    "speech-2.8-turbo",
    "kling-audio",
    "kling-custom-voices",
}


def is_yunwu_profile(parser_id: str) -> bool:
    return str(parser_id or "").strip().lower() == "yunwu_pricing_new"


def yunwu_multiplier(model_name: str, quota_type: int, model_ratio: float = 0.0) -> float:
    if not model_name:
        return 1.0

    if model_name == "grok-imagine-video" and quota_type in {1, 4}:
        return model_ratio if model_ratio > 0 else 20.0

    if quota_type == 1:
        return YUNWU_QUOTA1_MULTIPLIERS.get(model_name, 1.0)
    if quota_type == 4:
        return YUNWU_QUOTA4_MULTIPLIERS.get(model_name, 1.0)
    return 1.0


def yunwu_billing_profile(model_name: str, quota_type: int) -> BillingProfile:
    name = str(model_name or "")
    if quota_type == 0:
        return BillingProfile("Per token", "")
    if quota_type == 4:
        return BillingProfile("Per second", "s")
    if quota_type == 2 or name in YUNWU_IMAGE_MODELS:
        return BillingProfile("Per image", "image")
    if quota_type == 3 or name in YUNWU_VIDEO_MODELS:
        return BillingProfile("Per video", "video")
    if name.startswith("speech-") or name.startswith("qwen-tts") or name.startswith("qwen3-tts") or name in YUNWU_AUDIO_MODELS:
        return BillingProfile("Per audio", "audio")
    return BillingProfile("Per request", "request")

