"""Mail domain services and provider adapters."""

from .naver import Attachment, MailMessage, NaverMailConfig, NaverMailPoller
from .organizer import MailOrganizerConfig, MailOrganizerError, NaverMailOrganizer, UnreadMail

__all__ = (
    "Attachment",
    "MailMessage",
    "MailOrganizerConfig",
    "MailOrganizerError",
    "NaverMailConfig",
    "NaverMailOrganizer",
    "NaverMailPoller",
    "UnreadMail",
)
