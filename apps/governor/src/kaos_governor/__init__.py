"""Deterministic KaosGovernor services."""

__version__ = "0.1.0"
from .fax import FaxAction, FaxConfig, FaxError, FaxRequest, FaxService, normalize_destination, request_from_pdf

__all__ = (
    "FaxAction",
    "FaxConfig",
    "FaxError",
    "FaxRequest",
    "FaxService",
    "normalize_destination",
    "request_from_pdf",
)
