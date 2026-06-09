from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

HEX8 = re.compile(r"^[0-9A-F]{8}$")
HEX6 = re.compile(r"^[0-9A-F]{6}$")
XX_ID = re.compile(r"^(XX|xx)([0-9A-Fa-f]{6})$")
FE_ID = re.compile(r"^FE([0-9A-Fa-f]{3})([0-9A-Fa-f]{3})$")


@dataclass(slots=True)
class FormIdInfo:
    raw: str
    normalized: str
    object_id: str
    load_order: str
    kind: str
    plugin_name: str = ""
    resolved_id: str = ""
    warning: str = ""
    notes: str = ""

    def to_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("Input", self.raw),
            ("Normalized", self.normalized),
            ("Kind", self.kind),
            ("Load Order / Prefix", self.load_order),
            ("Object ID", self.object_id),
        ]
        if self.plugin_name:
            rows.append(("Plugin", self.plugin_name))
        if self.resolved_id:
            rows.append(("Resolved ID", self.resolved_id))
        if self.warning:
            rows.append(("Warning", self.warning))
        if self.notes:
            rows.append(("Notes", self.notes))
        return rows


def clean_id(value: str) -> str:
    return value.strip().replace("0x", "").replace("0X", "").replace(" ", "").upper()


def normalize_id(value: str) -> str:
    v = clean_id(value)
    if not v:
        return ""
    if XX_ID.match(v):
        return "XX" + v[2:].zfill(6)
    if re.fullmatch(r"[0-9A-F]{1,8}", v):
        return v.zfill(8)
    return v


PLUGIN_ALIASES = {
    "skyrim": "Skyrim.esm",
    "skyrimesm": "Skyrim.esm",
    "update": "Update.esm",
    "updateesm": "Update.esm",
    "dawnguard": "Dawnguard.esm",
    "dawnguardesm": "Dawnguard.esm",
    "dlc1": "Dawnguard.esm",
    "hearthfire": "HearthFires.esm",
    "hearthfires": "HearthFires.esm",
    "hearthfiresesm": "HearthFires.esm",
    "hearthfireesm": "HearthFires.esm",
    "dragonborn": "Dragonborn.esm",
    "dragonbornesm": "Dragonborn.esm",
    "dlc2dragonborn": "Dragonborn.esm",
}


def _plugin_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().casefold())


def infer_plugin_name(*texts: str) -> str:
    """Infer the owning official plugin from a source/name/editor-id bundle.

    DLC rows often arrive as XX123456 with source text from mixed sites.
    Prefer explicit DLC names/EditorID prefixes over generic source names like
    Skyrim.esm so an XX row whose notes say Dragonborn resolves to the loaded
    Dragonborn slot instead of 00.
    """
    joined = " ".join(t or "" for t in texts)
    key = _plugin_key(joined)
    upper = joined.upper()

    # Priority DLC checks first.
    if any(token in key for token in ("dawnguard", "dawnguardesm")) or "DLC1" in upper:
        return "Dawnguard.esm"
    if any(token in key for token in ("hearthfire", "hearthfires", "hearthfiresesm", "hearthfireesm")) or "BYOH" in upper:
        return "HearthFires.esm"
    if any(token in key for token in ("dragonborn", "dragonbornesm", "dlc2dragonborn")) or "DLC2" in upper:
        return "Dragonborn.esm"

    # Item-name fallbacks for rows imported from generic curated/source groups.
    dragonborn_words = (
        "stalhrim", "bonemold", "chitin", "netch", "ash", "skaal",
        "riekling", "moragtong", "telvanni", "redoran", "deathbrand",
        "ahlidons", "miraak", "blackbook", "seeker", "lurker",
    )
    dawnguard_words = (
        "crossbow", "bolt", "auriel", "vampireroyal", "bloodcursed",
        "sunhallowed", "falmerhardened", "falmerheavy", "shellbug",
    )
    hearthfire_words = (
        "quarriedstone", "sawnlog", "clay", "buildingmaterial",
        "byoh", "hearthfire",
    )
    if any(word in key for word in dragonborn_words):
        return "Dragonborn.esm"
    if any(word in key for word in dawnguard_words):
        return "Dawnguard.esm"
    if any(word in key for word in hearthfire_words):
        return "HearthFires.esm"

    if "updateesm" in key or key == "update":
        return "Update.esm"
    if "skyrimesm" in key or key == "skyrim":
        return "Skyrim.esm"
    return ""


def plugin_slot_for(plugin_name: str, plugins: Iterable[str]) -> int | None:
    wanted = plugin_name.strip()
    if not wanted:
        return None
    canonical = infer_plugin_name(wanted) or wanted
    wanted_key = _plugin_key(canonical)
    wanted_stem = _plugin_key(canonical.rsplit(".", 1)[0])
    for i, plugin in enumerate(plugins):
        plugin_key = _plugin_key(plugin)
        plugin_stem = _plugin_key(plugin.rsplit(".", 1)[0])
        if plugin_key == wanted_key or plugin_stem == wanted_stem:
            return i
    return None


def resolve_xx_id(value: str, plugin_name: str, plugins: Iterable[str]) -> str:
    norm = normalize_id(value)
    m = XX_ID.match(norm)
    if not m:
        return norm
    hint = infer_plugin_name(plugin_name) or plugin_name
    slot = plugin_slot_for(hint, plugins)
    if slot is None:
        return norm
    return f"{slot:02X}{m.group(2).upper()}"


def describe_form_id(value: str, plugin_name: str = "", plugins: Iterable[str] = ()) -> FormIdInfo:
    raw = value.strip()
    norm = normalize_id(raw)
    full_plugins = list(plugins)

    if not norm:
        return FormIdInfo(raw=raw, normalized="", object_id="", load_order="", kind="Empty")

    m_xx = XX_ID.match(norm)
    if m_xx:
        obj = m_xx.group(2).upper()
        resolved = resolve_xx_id(norm, plugin_name, full_plugins) if plugin_name else ""
        warning = "Select the owning plugin from the save plugin list to resolve XX."
        if resolved and not resolved.startswith("XX"):
            warning = "Resolved from the currently loaded save's plugin list."
        return FormIdInfo(
            raw=raw,
            normalized="XX" + obj,
            object_id=obj,
            load_order="XX",
            kind="Load-order placeholder ID",
            plugin_name=plugin_name,
            resolved_id=resolved if resolved != norm else "",
            warning=warning,
            notes="Use this for DLC/mod IDs that depend on load order. Do not save literal XX into a patch target.",
        )

    m_fe = FE_ID.match(norm)
    if m_fe:
        return FormIdInfo(
            raw=raw,
            normalized=norm,
            object_id=m_fe.group(2).upper(),
            load_order="FE " + m_fe.group(1).upper(),
            kind="Light plugin / ESL compact ID",
            warning="Light-plugin save references need extra care; this build identifies them but does not rewrite them yet.",
            notes="FE IDs use a compact light-plugin index plus a 3-hex object id.",
        )

    if HEX8.match(norm):
        prefix = norm[:2]
        obj = norm[2:]
        plugin = ""
        try:
            idx = int(prefix, 16)
            if 0 <= idx < len(full_plugins):
                plugin = full_plugins[idx]
        except ValueError:
            idx = -1
        if prefix == "00":
            kind = "Base-game FormID"
        elif prefix == "FF":
            kind = "Runtime/created reference range"
        else:
            kind = "Full FormID with load-order byte"
        notes = "First byte is the load-order/plugin slot; last 6 hex digits are the record object id."
        if plugin:
            notes += f" Plugin slot {prefix} is {plugin}."
        return FormIdInfo(
            raw=raw,
            normalized=norm,
            object_id=obj,
            load_order=prefix,
            kind=kind,
            plugin_name=plugin,
            notes=notes,
        )

    return FormIdInfo(
        raw=raw,
        normalized=norm,
        object_id="",
        load_order="",
        kind="Actor value / editor token / unknown",
        notes="This does not look like an 8-hex FormID. It may be an ActorValue token, cell/editor ID, quest variable, or plain name.",
    )


def base_reference_notes() -> str:
    return (
        "Base IDs identify the record/template, such as an item, spell, perk, NPC base, weather, faction, or quest. "
        "Reference IDs identify an instance placed in the world or in a save. Inventory add/edit work usually starts from base FormIDs; "
        "targeted commands and placed actors/objects usually use RefIDs. In save files, player inventory rows point to record IDs, while "
        "change forms and placed objects are tracked through compact RefIDs."
    )
