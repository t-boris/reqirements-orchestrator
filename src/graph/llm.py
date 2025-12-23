"""
LLM Factory - Simple LLM instantiation without state dependency.

Used by components that need LLM access but don't have RequirementState context.
"""

from langchain_core.language_models import BaseChatModel

from src.config.settings import get_settings

settings = get_settings()


def get_llm(model: str | None = None, temperature: float = 0.3) -> BaseChatModel:
    """
    Get an LLM instance by model name.

    Args:
        model: Model name (e.g., "gpt-4o", "claude-3-sonnet", "gemini-pro").
               Defaults to settings.default_llm_model.
        temperature: LLM temperature setting.

    Returns:
        Configured LLM instance.
    """
    from src.slack.channel_config_store import get_model_provider

    model_name = model or settings.default_llm_model
    provider = get_model_provider(model_name)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, temperature=temperature)
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    else:  # Default to OpenAI
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=temperature)
