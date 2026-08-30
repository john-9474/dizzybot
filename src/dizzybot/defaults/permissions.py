from __future__ import annotations

from typing import Any

from dizzybot.contracts import BasePermissionPolicy
from dizzybot.domain import GuildSettings
from dizzybot.errors import PermissionDeniedError, VoiceChannelError


class DefaultPermissionPolicy(BasePermissionPolicy):
    @staticmethod
    def _is_elevated(member: Any, settings: GuildSettings) -> bool:
        permissions = getattr(member, "guild_permissions", None)
        if permissions and (
            getattr(permissions, "administrator", False)
            or getattr(permissions, "manage_guild", False)
        ):
            return True
        if settings.dj_role_id is None:
            return False
        return any(getattr(role, "id", None) == settings.dj_role_id for role in member.roles)

    def voice_channel_for(
        self,
        interaction: Any,
        *,
        bot_channel_id: int | None,
        settings: GuildSettings,
    ) -> Any:
        if interaction.guild is None:
            raise VoiceChannelError("Music commands can only be used in a server.")
        member = interaction.user
        voice = getattr(member, "voice", None)
        channel = getattr(voice, "channel", None)
        elevated = self._is_elevated(member, settings)

        if bot_channel_id is None:
            if channel is None:
                raise VoiceChannelError()
            return channel
        if channel is not None and channel.id == bot_channel_id:
            return channel
        if elevated:
            return channel
        raise PermissionDeniedError("You must share the bot's voice channel to control playback.")

    def ensure_manage_guild(self, interaction: Any) -> None:
        if interaction.guild is None:
            raise PermissionDeniedError("Settings can only be changed in a server.")
        permissions = getattr(interaction.user, "guild_permissions", None)
        if not permissions or not (
            getattr(permissions, "administrator", False)
            or getattr(permissions, "manage_guild", False)
        ):
            raise PermissionDeniedError("The Manage Server permission is required.")

    def ensure_dj(self, interaction: Any, settings: GuildSettings) -> None:
        if interaction.guild is None:
            raise PermissionDeniedError("This command can only be used in a server.")
        member = interaction.user
        permissions = getattr(member, "guild_permissions", None)
        if permissions and getattr(permissions, "administrator", False):
            return
        if settings.dj_role_id is not None and any(
            getattr(role, "id", None) == settings.dj_role_id for role in member.roles
        ):
            return
        raise PermissionDeniedError("An administrator or the configured DJ role is required.")
