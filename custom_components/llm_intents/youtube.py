"""YouTube search tool for Home Assistant LLM integration."""

import logging
import mimetypes
from pathlib import Path

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
        "- Search for tutorials or other video content\n"
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
                    "duration": item.get("duration"),
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


class SearchMusicTool(BaseTool):
    """Tool for searching local music before falling back to YouTube."""

    name = "search_music"
    description = "Search Home Assistant's local music, then YouTube if not found."
    prompt_description = (
        "Always use `search_music` to find music. It searches local Home Assistant "
        "media first and only falls back to YouTube."
    )
    parameters = vol.Schema(
        {
            vol.Required("query", description="Song, artist, or album to find"): str,
            vol.Optional("num_results", default=1): vol.All(
                int, vol.Range(min=1, max=25)
            ),
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Search local audio files, then use duration-ranked YouTube results."""
        query = tool_input.tool_args["query"]
        num_results = tool_input.tool_args.get("num_results", 1)

        def search_local() -> list[dict]:
            terms = query.casefold().split()
            matches = []
            for source, media_dir in hass.config.media_dirs.items():
                root = Path(media_dir)
                for path in root.rglob("*"):
                    mime_type = mimetypes.guess_type(path.name)[0]
                    relative_path = path.relative_to(root)
                    if (
                        path.is_file()
                        and mime_type
                        and mime_type.startswith("audio/")
                        and all(term in str(relative_path).casefold() for term in terms)
                    ):
                        matches.append(
                            {
                                "title": path.stem,
                                "url": f"media-source://media_source/{source}/{relative_path.as_posix()}",
                                "source": "home_assistant",
                            }
                        )
            return matches[:num_results]

        try:
            local_results = await hass.async_add_executor_job(search_local)
        except OSError:
            _LOGGER.exception("Local music search encountered an error")
            local_results = []
        if local_results:
            return {"results": local_results, "instruction": "Use play_music."}

        candidate_count = min(25, max(10, num_results * 5))
        response = await SearchYouTubeTool(self.config, hass).async_call(
            hass,
            llm.ToolInput(
                tool_name="search_youtube",
                tool_args={
                    "query": f"{query} official audio",
                    "num_results": candidate_count,
                },
            ),
            llm_context,
        )
        results = response.get("results", [])
        results.sort(
            key=lambda item: (
                item.get("duration") is None,
                item.get("duration") or 0,
            )
        )
        response["results"] = results[:num_results]
        return response
