"""YouTube search tool for Home Assistant LLM integration."""

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType
from yt_dlp import YoutubeDL

from .base_tool import BaseTool
from .cache import SQLiteCache

_LOGGER = logging.getLogger(__name__)


class SearchYouTubeTool(BaseTool):
    """Tool for searching YouTube videos."""

    name = "search_youtube"

    description = (
        "Use this tool to search YouTube when the user requests or infers they want to:\n"
        "- Find a video to watch\n"
        "- Search for music, tutorials, or other video content\n"
        "- Play something on a TV or media player"
    )

    prompt_description = (
        "Use the `search_youtube` tool to find videos on YouTube:\n"
        "- Returns video titles, URLs, channel names, and descriptions.\n"
        "- Use this when the user wants to watch or play video content."
    )

    response_directive = (
        "Use the search results to answer the user's query.\n"
        "Use play_video for video playback or play_music for music playback."
    )

    parameters = vol.Schema(
        {
            vol.Required(
                "query",
                description="The search query for YouTube videos",
            ): str,
            vol.Optional(
                "num_results",
                default=1,
                description="Number of videos to return (1-25). Use more when the user wants multiple options.",
            ): vol.All(int, vol.Range(min=1, max=25)),
        },
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Call the tool."""
        query = tool_input.tool_args["query"]
        num_results = tool_input.tool_args.get("num_results", 1)

        try:
            cache = SQLiteCache()
            cache_params = {"query": query, "num_results": num_results}
            if cached_response := cache.get(__name__, cache_params):
                return cached_response

            data = await hass.async_add_executor_job(
                lambda: YoutubeDL(
                    {"extract_flat": True, "quiet": True},
                ).extract_info(f"ytsearch{num_results}:{query}", download=False),
            )
            results = [
                {
                    "title": item.get("title"),
                    "url": item.get("webpage_url") or item.get("url"),
                    "channel": item.get("channel") or item.get("uploader"),
                    "description": item.get("description"),
                    "published_at": item.get("upload_date"),
                }
                for item in (data or {}).get("entries", [])
                if item
            ]
            if not results:
                return {"result": "No videos found"}

            response = {"results": results, "instruction": self.response_directive}
            cache.set(__name__, cache_params, response)
            return response
        except Exception:
            _LOGGER.exception("YouTube search encountered an error")
            return {"error": "Error searching YouTube"}
