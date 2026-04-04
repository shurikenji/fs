"""
bot/services/api_clients/__init__.py — API Client Factory.
Returns the appropriate client based on server's api_type.
"""
from __future__ import annotations

import logging

from .base import BaseAPIClient
from .newapi import NewAPIClient
from .rixapi import RixAPIClient
from .other import OtherAPIClient

logger = logging.getLogger(__name__)

# Client registry
_CLIENTS: dict[str, type[BaseAPIClient]] = {
    "newapi": NewAPIClient,
    "rixapi": RixAPIClient,
    "other": OtherAPIClient,
}


def get_api_client(server: dict) -> BaseAPIClient:
    """
    Get appropriate API client based on server configuration.
    
    Args:
        server: Server config dict with 'api_type' field
        
    Returns:
        BaseAPIClient instance
        
    Examples:
        server = {"api_type": "newapi", ...} → NewAPIClient
        server = {"api_type": "rixapi", ...} → RixAPIClient
        server = {"api_type": "other", ...} → OtherAPIClient
    """
    api_type = server.get("api_type", "newapi").lower()
    
    client_class = _CLIENTS.get(api_type)
    if client_class is None:
        logger.warning(
            f"Unknown api_type '{api_type}', falling back to OtherAPIClient"
        )
        client_class = OtherAPIClient
    
    return client_class()


def get_api_client_by_type(api_type: str) -> BaseAPIClient:
    """
    Get API client by type name.
    
    Args:
        api_type: One of 'newapi', 'rixapi', 'other'
        
    Returns:
        BaseAPIClient instance
    """
    api_type = api_type.lower()
    
    client_class = _CLIENTS.get(api_type)
    if client_class is None:
        logger.warning(f"Unknown api_type '{api_type}', using OtherAPIClient")
        client_class = OtherAPIClient
    
    return client_class()


def register_client(api_type: str, client_class: type[BaseAPIClient]) -> None:
    """
    Register a custom API client.
    
    Args:
        api_type: Unique identifier for the API type
        client_class: Client class inheriting from BaseAPIClient
        
    Example:
        class MyCustomClient(BaseAPIClient):
            ...
        register_client("custom", MyCustomClient)
    """
    _CLIENTS[api_type.lower()] = client_class
    logger.info(f"Registered custom API client: {api_type}")


__all__ = [
    "BaseAPIClient",
    "NewAPIClient",
    "RixAPIClient",
    "OtherAPIClient",
    "get_api_client",
    "get_api_client_by_type",
    "register_client",
]
