"""Typed errors safe to convert into user-facing responses."""


class DizzyBotError(Exception):
    default_message = "DizzyBot could not complete that request."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)


class InvalidRequestError(DizzyBotError):
    default_message = "That request is not valid."


class PermissionDeniedError(DizzyBotError):
    default_message = "You do not have permission to do that."


class VoiceChannelError(DizzyBotError):
    default_message = "Join a voice channel before using that command."


class SourceUnavailableError(DizzyBotError):
    default_message = "That media source is not configured."


class MediaUnavailableError(DizzyBotError):
    default_message = "No playable tracks were found."


class QueueLimitError(DizzyBotError):
    default_message = "The queue does not have room for those tracks."


class PlayerStateError(DizzyBotError):
    default_message = "There is no active player for this server."


class AudioBackendError(DizzyBotError):
    default_message = "The audio service is unavailable."
