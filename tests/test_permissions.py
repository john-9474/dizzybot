from types import SimpleNamespace

import pytest

from dizzybot.defaults.permissions import DefaultPermissionPolicy
from dizzybot.domain import GuildSettings
from dizzybot.errors import PermissionDeniedError, VoiceChannelError


def member(
    *,
    channel_id: int | None,
    administrator: bool = False,
    manage_guild: bool = False,
    roles: tuple[int, ...] = (),
) -> SimpleNamespace:
    channel = SimpleNamespace(id=channel_id) if channel_id is not None else None
    return SimpleNamespace(
        voice=SimpleNamespace(channel=channel) if channel else None,
        guild_permissions=SimpleNamespace(
            administrator=administrator,
            manage_guild=manage_guild,
        ),
        roles=[SimpleNamespace(id=role_id) for role_id in roles],
    )


def interaction(user: SimpleNamespace, *, guild: bool = True) -> SimpleNamespace:
    return SimpleNamespace(guild=SimpleNamespace() if guild else None, user=user)


def test_voice_permissions_require_channel_and_allow_elevated_remote() -> None:
    policy = DefaultPermissionPolicy()
    settings = GuildSettings(guild_id=1, dj_role_id=7)
    same = member(channel_id=5)
    assert policy.voice_channel_for(interaction(same), bot_channel_id=5, settings=settings).id == 5
    with pytest.raises(PermissionDeniedError):
        policy.voice_channel_for(
            interaction(member(channel_id=6)), bot_channel_id=5, settings=settings
        )
    assert (
        policy.voice_channel_for(
            interaction(member(channel_id=6, roles=(7,))),
            bot_channel_id=5,
            settings=settings,
        ).id
        == 6
    )
    assert (
        policy.voice_channel_for(
            interaction(member(channel_id=None, administrator=True)),
            bot_channel_id=5,
            settings=settings,
        )
        is None
    )


def test_voice_permissions_reject_dm_or_disconnected_member() -> None:
    policy = DefaultPermissionPolicy()
    settings = GuildSettings(guild_id=1)
    with pytest.raises(VoiceChannelError, match="server"):
        policy.voice_channel_for(
            interaction(member(channel_id=1), guild=False),
            bot_channel_id=None,
            settings=settings,
        )
    with pytest.raises(VoiceChannelError, match="Join"):
        policy.voice_channel_for(
            interaction(member(channel_id=None)), bot_channel_id=None, settings=settings
        )


def test_manage_guild_permission() -> None:
    policy = DefaultPermissionPolicy()
    policy.ensure_manage_guild(interaction(member(channel_id=None, manage_guild=True)))
    with pytest.raises(PermissionDeniedError, match="Manage Server"):
        policy.ensure_manage_guild(interaction(member(channel_id=None)))
    with pytest.raises(PermissionDeniedError, match="server"):
        policy.ensure_manage_guild(
            interaction(member(channel_id=None, administrator=True), guild=False)
        )


def test_24_7_mode_requires_dj_role_or_administrator() -> None:
    policy = DefaultPermissionPolicy()
    settings = GuildSettings(guild_id=1, dj_role_id=7)
    policy.ensure_dj(interaction(member(channel_id=None, roles=(7,))), settings)
    policy.ensure_dj(interaction(member(channel_id=None, administrator=True)), settings)

    with pytest.raises(PermissionDeniedError, match="DJ role"):
        policy.ensure_dj(interaction(member(channel_id=None, manage_guild=True)), settings)
    with pytest.raises(PermissionDeniedError, match="server"):
        policy.ensure_dj(interaction(member(channel_id=None, roles=(7,)), guild=False), settings)
