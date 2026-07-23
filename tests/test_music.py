"""Tests for music search and playback."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from custom_components.llm_intents.play_music import PlayMusicTool
from custom_components.llm_intents.youtube import SearchMusicTool


def tool_input(name: str, args: dict) -> llm.ToolInput:
    """Create tool input."""
    return llm.ToolInput(tool_name=name, tool_args=args)


async def test_search_music_prefers_local(hass: HomeAssistant, tmp_path: Path) -> None:
    """Return local music without searching YouTube."""
    track = tmp_path / "Artist - Song.mp3"
    track.write_bytes(b"audio")
    hass.config.media_dirs = {"local": str(tmp_path)}

    with patch(
        "custom_components.llm_intents.youtube.SearchYouTubeTool.async_call",
        new_callable=AsyncMock,
    ) as youtube_search:
        result = await SearchMusicTool({}, hass).async_call(
            hass,
            tool_input("search_music", {"query": "artist song"}),
            AsyncMock(),
        )

    youtube_search.assert_not_called()
    assert result["results"][0]["url"] == (
        "media-source://media_source/local/Artist - Song.mp3"
    )


async def test_search_music_fallback_prefers_shorter_videos(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Rank YouTube fallback results by duration."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    youtube_results = {
        "results": [
            {"title": "Long", "duration": 500},
            {"title": "Unknown", "duration": None},
            {"title": "Short", "duration": 180},
        ]
    }

    with patch(
        "custom_components.llm_intents.youtube.SearchYouTubeTool.async_call",
        new_callable=AsyncMock,
        return_value=youtube_results,
    ) as youtube_search:
        result = await SearchMusicTool({}, hass).async_call(
            hass,
            tool_input("search_music", {"query": "song", "num_results": 2}),
            AsyncMock(),
        )

    assert [item["title"] for item in result["results"]] == ["Short", "Long"]
    assert youtube_search.await_args.args[1].tool_args["query"] == "song official audio"


async def test_play_music_resolves_local_media(hass: HomeAssistant) -> None:
    """Resolve Home Assistant media source IDs before playback."""
    resolved = Mock(url="/media/local/song.mp3")
    hass.services.async_call = AsyncMock()

    with (
        patch(
            "custom_components.llm_intents.play_music.media_source.async_resolve_media",
            new_callable=AsyncMock,
            return_value=resolved,
        ),
        patch(
            "custom_components.llm_intents.play_music.async_process_play_media_url",
            return_value="http://home/media/local/song.mp3",
        ),
    ):
        result = await PlayMusicTool({}, hass).async_call(
            hass,
            tool_input(
                "play_music",
                {
                    "music_url": "media-source://media_source/local/song.mp3",
                    "entity_id": "media_player.speaker",
                },
            ),
            AsyncMock(),
        )

    assert result["success"] is True
    hass.services.async_call.assert_awaited_once()
