from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from dizzybot.domain import GuildSettings


class BasePermissionPolicy(ABC):
    @abstractmethod
    def voice_channel_for(
        self,
        interaction: Any,
        *,
        bot_channel_id: int | None,
        settings: GuildSettings,
    ) -> Any: ...

    @abstractmethod
    def ensure_manage_guild(self, interaction: Any) -> None: ...

    @abstractmethod
    def ensure_dj(self, interaction: Any, settings: GuildSettings) -> None: ...
