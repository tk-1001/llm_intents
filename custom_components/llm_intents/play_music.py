"""Play music tool for Tools for Assist integration."""

import logging

import voluptuous as vol
from homeassistant.components import media_source
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    async_process_play_media_url,
)
from homeassistant.const import ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
from homeassistant.util.json import JsonObjectType
from yt_dlp import YoutubeDL

from .base_tool import BaseTool

_LOGGER = logging.getLogger(__name__)


class PlayMusicTool(BaseTool):
    """Tool for resolving and playing music on a media player."""

    name = "play_music"
    description = (
        "Resolve a music URL or Home Assistant media source and play it on a "
        "media player."
    )
    prompt_description = (
        "Use `play_music` with a result from `search_music` and a media player "
        "entity when the user wants to listen to music."
    )
    parameters = vol.Schema({})

    @staticmethod
    def update_args(hass: HomeAssistant) -> None:
        """Update the available media players."""
        entities = er.async_get(hass).entities
        players = [
            entry.entity_id
            for entry in entities.values()
            if entry.entity_id.startswith("media_player.")
            and (state := hass.states.get(entry.entity_id))
            and state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)
            & MediaPlayerEntityFeature.PLAY_MEDIA
        ]
        PlayMusicTool.parameters = vol.Schema(
            {
                vol.Required(
                    "music_url",
                    description="The music URL or media source ID to play",
                ): str,
                vol.Required(
                    "entity_id",
                    description="The target media player entity",
                ): SelectSelector(SelectSelectorConfig(options=players)),
            }
        )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Resolve the audio stream and play it through Home Assistant."""
        music_url = tool_input.tool_args["music_url"]
        entity_id = tool_input.tool_args["entity_id"]

        try:
            if media_source.is_media_source_id(music_url):
                media = await media_source.async_resolve_media(
                    hass, music_url, entity_id
                )
                stream_url = async_process_play_media_url(hass, media.url)
            else:
                info = await hass.async_add_executor_job(
                    lambda: YoutubeDL(
                        {
                            "format": "bestaudio[protocol^=http]/bestaudio/best",
                            "noplaylist": True,
                            "quiet": True,
                        }
                    ).extract_info(music_url, download=False)
                )
                stream_url = info.get("url") if info else None
            if not stream_url:
                return {"success": False, "error": "No playable audio stream found"}

            await hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "media_content_id": stream_url,
                    "media_content_type": "music",
                },
                target={"entity_id": entity_id},
                blocking=True,
            )
            return {
                "success": True,
                "message": f"Now playing music on {entity_id}",
            }
        except Exception as err:
            _LOGGER.exception("Failed to play music on %s", entity_id)
            return {
                "success": False,
                "error": f"Failed to play music on {entity_id}: {err}",
            }
