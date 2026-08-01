"""One-time (re-runnable) sync of app/agents/prompts.py's local prompt text
into Langfuse Prompt Management, labeled "production".

app/agents/prompts.py resolves `prompts.SOME_PROMPT` from Langfuse at call
time with the local `_SOME_PROMPT` string as a fallback (see that module's
docstring) - so the app works fine without ever running this script. Run it
to seed/update Langfuse with the current code-defined prompt text as a
starting point, after which prompts can be edited/versioned from the
Langfuse UI without a redeploy.

Usage (from backend/):
    python -m scripts.sync_prompts_to_langfuse
"""
import logging
import sys

from app.agents import prompts
from app.core import observability

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("sync_prompts")


def _local_prompts() -> dict[str, str]:
    """Every _PUBLIC_NAME constant in prompts.py, keyed by its public name -
    i.e. exactly the set that prompts.py's __getattr__ can fall back to."""
    return {
        name[1:]: value
        for name, value in vars(prompts).items()
        if name.startswith("_") and name[1:].isupper() and isinstance(value, str)
    }


def main() -> int:
    client = observability.get_langfuse_client()
    if client is None:
        logger.error(
            "Langfuse client unavailable - check ENABLE_LANGFUSE_TRACING, "
            "LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY/LANGFUSE_HOST in backend/.env."
        )
        return 1

    local_prompts = _local_prompts()
    logger.info(f"Syncing {len(local_prompts)} prompts to {observability.settings.LANGFUSE_HOST} ...")

    failures = []
    for public_name, text in sorted(local_prompts.items()):
        langfuse_name = public_name.lower().replace("_", "-")
        try:
            client.create_prompt(name=langfuse_name, prompt=text, labels=["production"], type="text")
            logger.info(f"  ok   {langfuse_name}")
        except Exception as e:
            failures.append(langfuse_name)
            logger.error(f"  FAIL {langfuse_name}: {e}")

    client.flush()

    if failures:
        logger.error(f"{len(failures)} prompt(s) failed to sync: {failures}")
        return 1

    logger.info("All prompts synced successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
