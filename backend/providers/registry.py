"""
ProviderRegistry — singleton dynamic registration and dependency injection.
All routers and services obtain providers via this registry.
"""
from __future__ import annotations

from importlib import import_module
import logging
import time
from typing import Any, TypeVar

from providers.base import ProviderBase

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=ProviderBase)


class ProviderRegistry:
    """
    Singleton registry for all provider instances.

    Usage:
        registry = get_registry()
        caption_provider = registry.get("caption", "ollama")
    """

    _instance: ProviderRegistry | None = None

    def __init__(self) -> None:
        # { provider_type: { name: provider_class } }
        self._classes: dict[str, dict[str, type[ProviderBase]]] = {}
        # { provider_type: { name: provider_instance } } — lazy init
        self._instances: dict[str, dict[str, ProviderBase]] = {}
        # { provider_type: { name: config_dict } }
        self._configs: dict[str, dict[str, dict[str, Any]]] = {}
        self._availability_cache: dict[tuple[str, str], tuple[float, bool]] = {}
        self._availability_ttl_seconds = 5.0

    @classmethod
    def instance(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        provider_type: str,
        name: str,
        provider_class: type[ProviderBase],
        config: dict[str, Any] | None = None,
    ) -> None:
        """Register a provider class under a type + name."""
        if provider_type not in self._classes:
            self._classes[provider_type] = {}
            self._configs[provider_type] = {}
        self._classes[provider_type][name] = provider_class
        self._configs[provider_type][name] = config or {}
        # Invalidate cached instance if re-registering
        if provider_type in self._instances and name in self._instances[provider_type]:
            del self._instances[provider_type][name]
        self._availability_cache.pop((provider_type, name), None)
        logger.debug("Registered provider %s/%s", provider_type, name)

    def set_config(
        self, provider_type: str, name: str, config: dict[str, Any]
    ) -> None:
        """Update config for a registered provider (invalidates instance)."""
        if provider_type not in self._configs:
            self._configs[provider_type] = {}
        self._configs[provider_type][name] = config
        # Invalidate so the instance is recreated with new config
        if provider_type in self._instances and name in self._instances[provider_type]:
            del self._instances[provider_type][name]
        self._availability_cache.pop((provider_type, name), None)

    # ── Access ─────────────────────────────────────────────────────────────────

    def get(self, provider_type: str, name: str) -> ProviderBase | None:
        """Return the provider instance, lazily instantiated."""
        if provider_type not in self._classes:
            return None
        if name not in self._classes[provider_type]:
            return None

        # Lazy instantiation
        if provider_type not in self._instances:
            self._instances[provider_type] = {}

        if name not in self._instances[provider_type]:
            cls = self._classes[provider_type][name]
            cfg = self._configs.get(provider_type, {}).get(name, {})
            try:
                self._instances[provider_type][name] = cls(**cfg)
                logger.debug("Instantiated provider %s/%s", provider_type, name)
            except Exception as exc:
                logger.error(
                    "Failed to instantiate provider %s/%s: %s", provider_type, name, exc
                )
                return None

        return self._instances[provider_type][name]

    def get_typed(self, provider_type: str, name: str, cls: type[T]) -> T | None:
        """Type-safe get."""
        provider = self.get(provider_type, name)
        if provider is None:
            return None
        if not isinstance(provider, cls):
            logger.warning(
                "Provider %s/%s is %s, expected %s",
                provider_type, name, type(provider).__name__, cls.__name__,
            )
            return None
        return provider  # type: ignore[return-value]

    def get_default(self, provider_type: str) -> ProviderBase | None:
        """Return the first registered provider for a type, if any."""
        if provider_type not in self._classes:
            return None
        names = list(self._classes[provider_type].keys())
        if not names:
            return None
        return self.get(provider_type, names[0])

    def list_available(self, provider_type: str) -> list[str]:
        """Return list of registered provider names for a type."""
        return list(self._classes.get(provider_type, {}).keys())

    def list_all_types(self) -> list[str]:
        return list(self._classes.keys())

    # ── Health ─────────────────────────────────────────────────────────────────

    async def health_check_all(self) -> dict[str, dict[str, Any]]:
        """Run health_check() on all registered providers. Returns nested dict."""
        results: dict[str, dict[str, Any]] = {}
        for ptype, names in self._classes.items():
            results[ptype] = {}
            for name in names:
                provider = self.get(ptype, name)
                if provider is None:
                    results[ptype][name] = {"ok": False, "error": "failed to instantiate"}
                    continue
                try:
                    results[ptype][name] = await provider.health_check()
                except Exception as exc:
                    results[ptype][name] = {"ok": False, "error": str(exc)}
        return results

    async def check_available(
        self, provider_type: str, name: str
    ) -> bool:
        """Return True if the named provider is available right now."""
        cache_key = (provider_type, name)
        cached = self._availability_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < self._availability_ttl_seconds:
            return cached[1]

        provider = self.get(provider_type, name)
        if provider is None:
            return False
        try:
            is_available = await provider.is_available()
            self._availability_cache[cache_key] = (now, is_available)
            return is_available
        except Exception:
            self._availability_cache[cache_key] = (now, False)
            return False

    # ── Bulk operations ────────────────────────────────────────────────────────

    async def load_all(self) -> None:
        """Pre-warm all registered providers."""
        for ptype, names in self._classes.items():
            for name in names:
                provider = self.get(ptype, name)
                if provider is None:
                    continue
                try:
                    await provider.load()
                    logger.info("Loaded provider %s/%s", ptype, name)
                except Exception as exc:
                    logger.warning(
                        "Could not pre-warm provider %s/%s: %s", ptype, name, exc
                    )

    def __repr__(self) -> str:
        types = {k: list(v.keys()) for k, v in self._classes.items()}
        return f"ProviderRegistry({types})"


def get_registry() -> ProviderRegistry:
    """Module-level accessor for the singleton registry."""
    return ProviderRegistry.instance()


def safe_register_provider(
    registry: ProviderRegistry,
    provider_type: str,
    name: str,
    module_path: str,
    class_name: str,
    *,
    catch: tuple[type[BaseException], ...] = (Exception,),
) -> bool:
    """Import and register a provider through one consistent startup path."""
    try:
        module = import_module(module_path)
        provider_class = getattr(module, class_name)
        registry.register(provider_type, name, provider_class)
        logger.info("Registered %s/%s", provider_type, name)
        return True
    except catch as exc:
        logger.warning("Could not register %s/%s: %s", provider_type, name, exc)
        return False


# ── Default provider registration ─────────────────────────────────────────────

def register_default_providers(registry: ProviderRegistry) -> None:
    """Register all built-in providers. Called during app startup."""

    # Storage
    try:
        from providers.storage.local import LocalStorageProvider
        registry.register("storage", "local", LocalStorageProvider)
        logger.info("Registered storage/local")
    except ImportError as e:
        logger.warning("Could not register storage/local: %s", e)

    # Quality
    try:
        from providers.quality.composite import CompositeQualityScorer
        registry.register("quality", "composite", CompositeQualityScorer)
        logger.info("Registered quality/composite")
    except ImportError as e:
        logger.warning("Could not register quality/composite: %s", e)

    # Embedding
    try:
        from providers.embedding.fastembed import FastEmbedProvider
        registry.register("embedding", "fastembed", FastEmbedProvider)
        logger.info("Registered embedding/fastembed")
    except ImportError as e:
        logger.warning("Could not register embedding/fastembed: %s", e)

    # Face detection
    try:
        from providers.face.insightface import InsightFaceProvider
        registry.register("face_detection", "insightface", InsightFaceProvider)
        logger.info("Registered face_detection/insightface")
    except ImportError as e:
        logger.warning("Could not register face_detection/insightface: %s", e)

    # Caption — Ollama (always try; Ollama may not be running)
    try:
        from providers.caption.ollama import OllamaCaptionProvider
        registry.register("caption", "ollama", OllamaCaptionProvider)
        logger.info("Registered caption/ollama")
    except ImportError as e:
        logger.warning("Could not register caption/ollama: %s", e)

    # Caption — Gemini (only if key available)
    try:
        from providers.caption.gemini import GeminiCaptionProvider
        registry.register("caption", "gemini", GeminiCaptionProvider)
        logger.info("Registered caption/gemini")
    except ImportError as e:
        logger.warning("Could not register caption/gemini: %s", e)

    # Caption — OpenAI (only if key available)
    try:
        from providers.caption.openai import OpenAICaptionProvider
        registry.register("caption", "openai", OpenAICaptionProvider)
        logger.info("Registered caption/openai")
    except ImportError as e:
        logger.warning("Could not register caption/openai: %s", e)

    # Caption — JoyCaption (local HuggingFace VLM, primary local path)
    try:
        from providers.caption.joycaption import JoyCaptionProvider
        registry.register("caption", "joycaption", JoyCaptionProvider)
        logger.info("Registered caption/joycaption")
    except Exception as e:
        logger.warning("Could not register caption/joycaption: %s", e)

    # Caption — Qwen2.5-VL (local HuggingFace VLM, deep reasoning)
    try:
        from providers.caption.qwen_vl import QwenVLProvider
        registry.register("caption", "qwen_vl", QwenVLProvider)
        logger.info("Registered caption/qwen_vl")
    except Exception as e:
        logger.warning("Could not register caption/qwen_vl: %s", e)

    # Caption — Moondream2 (lightweight fallback, CPU-capable)
    try:
        from providers.caption.moondream import MoondreamProvider
        registry.register("caption", "moondream", MoondreamProvider)
        logger.info("Registered caption/moondream")
    except Exception as e:
        logger.warning("Could not register caption/moondream: %s", e)

    # Caption — LM Studio (local OpenAI-compatible server)
    try:
        from providers.caption.lmstudio import LMStudioCaptionProvider
        registry.register("caption", "lmstudio", LMStudioCaptionProvider)
        logger.info("Registered caption/lmstudio")
    except Exception as e:
        logger.warning("Could not register caption/lmstudio: %s", e)

    # Export providers
    try:
        from providers.export.lora_exporter import LoRAExporter
        registry.register("export", "lora_exporter", LoRAExporter)
        logger.info("Registered export/lora_exporter")
    except Exception as e:
        logger.warning("Could not register export/lora_exporter: %s", e)

    try:
        from providers.export.kohya_exporter import KohyaExporter
        registry.register("export", "kohya_exporter", KohyaExporter)
        logger.info("Registered export/kohya_exporter")
    except Exception as e:
        logger.warning("Could not register export/kohya_exporter: %s", e)

    try:
        from providers.export.zip_exporter import ZipExporter
        registry.register("export", "zip_exporter", ZipExporter)
        logger.info("Registered export/zip_exporter")
    except Exception as e:
        logger.warning("Could not register export/zip_exporter: %s", e)


def register_optional_providers(registry: ProviderRegistry) -> None:
    """Register optional providers that extend the default local workflow."""
    safe_register_provider(
        registry, "caption", "llava_next", "providers.caption.llava_next", "LLaVANextProvider"
    )
    safe_register_provider(
        registry, "caption", "florence2", "providers.caption.florence2", "Florence2CaptionProvider"
    )
    safe_register_provider(
        registry,
        "quality",
        "laion_aesthetic",
        "providers.quality.laion_aesthetic",
        "LAIONAestheticProvider",
    )
    safe_register_provider(
        registry,
        "upscaling",
        "realesrgan",
        "providers.editing.realesrgan",
        "RealESRGANProvider",
    )
    safe_register_provider(
        registry, "pose", "mmpose", "providers.pose.mmpose_provider", "MMPoseProvider"
    )
    safe_register_provider(
        registry,
        "head_pose",
        "openface",
        "providers.face.openface_provider",
        "OpenFaceProvider",
    )
    safe_register_provider(
        registry,
        "action_units",
        "openface",
        "providers.face.openface_provider",
        "OpenFaceProvider",
    )
    safe_register_provider(
        registry,
        "scene_understanding",
        "clip_scene",
        "providers.scene.clip_scene",
        "CLIPSceneProvider",
    )
