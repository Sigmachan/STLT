from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SettingOption:
    key: str
    label: str
    option_type: str
    default: Any
    description: str = ""
    choices: Optional[List[Dict[str, Any]]] = None
    requires_restart: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SettingGroup:
    key: str
    label: str
    description: str
    options: List[SettingOption]


SETTINGS_GROUPS: List[SettingGroup] = [
    SettingGroup(
        key="general",
        label="General",
        description="Global LuaTools preferences.",
        options=[
            SettingOption(
                key="useSteamLanguage",
                label="Use Steam Language",
                option_type="toggle",
                description="Use the Steam client's language for LuaTools.",
                default=True,
                metadata={"yesLabel": "Yes", "noLabel": "No"},
            ),
            SettingOption(
                key="language",
                label="Language",
                option_type="select",
                description="Choose the language used by LuaTools.",
                default="en",
                metadata={"dynamicChoices": "locales"},
            ),
            SettingOption(
                key="donateKeys",
                label="Donate Keys",
                option_type="toggle",
                description="Allow LuaTools to donate spare Steam keys. (placeholder option)",
                default=True,
                metadata={"yesLabel": "Yes", "noLabel": "No"},
            ),
            SettingOption(
                key="theme",
                label="Theme",
                option_type="select",
                description="Choose the color theme for LuaTools interface.",
                default="original",
                metadata={"dynamicChoices": "themes"},
            ),
            SettingOption(
                key="morrenusApiKey",
                label="Morrenus API Key",
                option_type="text",
                description="API Key required to use Sadie Source. Get from manifest.morrenus.xyz",
                default="",
                metadata={"placeholder": "Enter your API key..."},
            ),
            SettingOption(
                key="ryuuSession",
                label="Ryuu Premium Session Cookie",
                option_type="text",
                description="Your 'session' cookie from generator.ryuu.lol (Premium). Tried first before all other sources.",
                default="",
                metadata={"placeholder": "Paste session cookie value..."},
            ),
            SettingOption(
                key="depotboxSid",
                label="DepotBox Premium Cookie",
                option_type="text",
                description="Your 'connect.sid' cookie from depotbox.org (Premium). Tried second after Ryuu.",
                default="",
                metadata={"placeholder": "Paste connect.sid value..."},
            ),
        ],
    ),
    SettingGroup(
        key="steamtools",
        label="SteamTools",
        description="SteamTools collection sync, cache management and backups.",
        options=[
            SettingOption(
                key="collectionName",
                label="Collection Name",
                option_type="text",
                description="Name of the Steam collection to sync added games into.",
                default="Steamtools",
                metadata={"placeholder": "Steamtools"},
            ),
            SettingOption(
                key="collectionReplace",
                label="Replace Collection on Sync",
                option_type="toggle",
                description="Clear the collection before adding current games (mirrors clemdotla behavior).",
                default=True,
                metadata={"yesLabel": "Yes", "noLabel": "No"},
            ),
            SettingOption(
                key="showDisabledInCollection",
                label="Include Disabled Scripts",
                option_type="toggle",
                description="Include .lua.disabled scripts in the collection sync.",
                default=False,
                metadata={"yesLabel": "Yes", "noLabel": "No"},
            ),
            SettingOption(
                key="autoAuditOnInstall",
                label="Auto-Audit After Install",
                option_type="toggle",
                description="Automatically check depot/DLC/workshop completeness after installing a .lua.",
                default=True,
                metadata={"yesLabel": "Yes", "noLabel": "No"},
            ),
            SettingOption(
                key="localManifestPath",
                label="Local Manifest Folder",
                option_type="text",
                description="Path to a local folder with .lua/.zip manifests. Checked BEFORE any network source (Priority 0). Leave empty to disable.",
                default="",
                metadata={"placeholder": r"C:\Users\You\manifests"},
            ),
            SettingOption(
                key="manifestHubApiKey",
                label="ManifestHub API Key",
                option_type="text",
                description="For direct ManifestHub manifest downloads. Get yours at manifesthub.filegear-sg.me",
                default="",
                metadata={"placeholder": "mh_xxxxxxxxxx"},
            ),
            SettingOption(
                key="steamGridDbKey",
                label="SteamGridDB API Key",
                option_type="text",
                description="For high-quality game artwork in overlays. Get yours at steamgriddb.com/profile/preferences/api",
                default="",
                metadata={"placeholder": "b38eb1dc..."},
            ),
            SettingOption(
                key="githubToken",
                label="GitHub Token (optional)",
                option_type="text",
                description="Personal access token for GitHub API. Raises rate limit from 60 to 5000 req/h for SDO manifest repos. github.com/settings/tokens",
                default="",
                metadata={"placeholder": "ghp_xxxxxxxxxxxx"},
            ),
        ],
    ),
]


def get_settings_schema() -> List[Dict[str, Any]]:
    """Return a serialisable representation of the settings schema."""
    schema: List[Dict[str, Any]] = []
    for group in SETTINGS_GROUPS:
        schema.append(
            {
                "key": group.key,
                "label": group.label,
                "description": group.description,
                "options": [
                    {
                        "key": option.key,
                        "label": option.label,
                        "type": option.option_type,
                        "description": option.description,
                        "default": option.default,
                        "choices": option.choices or [],
                        "requiresRestart": option.requires_restart,
                        "metadata": option.metadata,
                    }
                    for option in group.options
                ],
            }
        )
    return schema


def get_default_settings_values() -> Dict[str, Any]:
    """Return a flat dictionary of option defaults, namespaced by group."""
    defaults: Dict[str, Any] = {}
    for group in SETTINGS_GROUPS:
        group_defaults: Dict[str, Any] = {}
        for option in group.options:
            group_defaults[option.key] = option.default
        defaults[group.key] = group_defaults
    return defaults


def merge_defaults_with_values(values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge provided values with defaults, returning a dictionary that includes
    all current schema keys. Extra keys in `values` are preserved to avoid
    data loss when options are removed.
    """
    merged = values.copy() if isinstance(values, dict) else {}
    defaults = get_default_settings_values()

    for group_key, group_defaults in defaults.items():
        existing_group = merged.get(group_key)
        if not isinstance(existing_group, dict):
            existing_group = {}
        # Preserve unknown keys within the group.
        merged_group = {**group_defaults, **existing_group}
        merged[group_key] = merged_group

    return merged
