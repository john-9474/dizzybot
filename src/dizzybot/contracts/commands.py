from typing import Any


class BaseMusicCommands:
    async def register(self, bot: Any) -> None:
        raise NotImplementedError


class BaseSettingsCommands:
    async def register(self, bot: Any) -> None:
        raise NotImplementedError


class BaseRadioCommands:
    async def register(self, bot: Any) -> None:
        raise NotImplementedError
