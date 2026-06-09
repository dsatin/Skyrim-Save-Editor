from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

COMMANDS = [
    "player.additem",
    "player.removeitem",
    "player.addperk",
    "player.removeperk",
    "player.addspell",
    "player.removespell",
    "player.teachword",
    "player.unlockword",
    "player.setav",
    "player.modav",
    "player.forceav",
]

COMMANDS_WITH_AMOUNT = {
    "player.additem",
    "player.removeitem",
    "player.setav",
    "player.modav",
    "player.forceav",
}

COMMANDS_WITHOUT_AMOUNT = {
    "player.addperk",
    "player.removeperk",
    "player.addspell",
    "player.removespell",
    "player.teachword",
    "player.unlockword",
}


@dataclass(slots=True)
class ConsoleCommandPreset:
    label: str
    command: str
    target: str
    amount: int | None = None
    notes: str = ""

    def line(self) -> str:
        return build_console_command(self.command, self.target, self.amount or 1)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_form_or_actor_value(value: str) -> str:
    clean = value.strip()
    if not clean:
        return clean
    # Keep actor values readable, but normalize hex IDs for comparison/search.
    hexish = clean.replace("0x", "").replace("0X", "").replace(" ", "")
    if len(hexish) <= 8 and all(c in "0123456789abcdefABCDEF" for c in hexish):
        return hexish.upper().zfill(8)
    return clean


def build_console_command(command: str, target: str, amount: int | float | None = 1) -> str:
    cmd = command.strip().lower()
    if cmd not in COMMANDS:
        raise ValueError(f"Unsupported command: {command}")
    target = normalize_form_or_actor_value(target)
    if not target:
        raise ValueError("Missing FormID, perk/spell ID, or actor value")
    if cmd in COMMANDS_WITH_AMOUNT:
        if amount is None:
            amount = 1
        return f"{cmd} {target} {amount}"
    return f"{cmd} {target}"


def default_presets() -> list[ConsoleCommandPreset]:
    return [
        ConsoleCommandPreset("Gold 1,000", "player.additem", "0000000F", 1000, "Small gold delta for save diffing"),
        ConsoleCommandPreset("Gold 10,000", "player.additem", "0000000F", 10000, "Larger gold test"),
        ConsoleCommandPreset("Lockpicks 10", "player.additem", "0000000A", 10, "Simple stackable item test"),
        ConsoleCommandPreset("Lockpicks 100", "player.additem", "0000000A", 100, "Bigger stackable item test"),
        ConsoleCommandPreset("CarryWeight 9999", "player.forceav", "carryweight", 9999, "Actor value persistence test"),
        ConsoleCommandPreset("Health 999", "player.forceav", "health", 999, "Actor value persistence test"),
        ConsoleCommandPreset("Smithing 100", "player.setav", "smithing", 100, "Skill actor value test"),
        ConsoleCommandPreset("One perk test", "player.addperk", "000CB40D", None, "Single perk record discovery test"),
        ConsoleCommandPreset("Teach Fus word", "player.teachword", "00013E22", None, "Word-of-Power command test"),
        ConsoleCommandPreset("Unlock Fus word", "player.unlockword", "00013E22", None, "Requires dragon soul in-game"),
    ]


def diff_study_script() -> str:
    lines = [
        "; Skyrim Save Lab controlled test script",
        "; 1) Make a clean baseline save first and close the menu.",
        "; 2) Run ONE block, save again, then compare baseline vs changed save.",
        "",
        "; Gold delta",
        "player.additem 0000000F 1000",
        "",
        "; Lockpick stack delta",
        "player.additem 0000000A 10",
        "",
        "; Actor value delta",
        "player.forceav carryweight 9999",
        "",
        "; Skill delta",
        "player.setav smithing 100",
        "",
        "; Useful helper commands",
        "player.showinventory",
        "help gold 0",
        "help lockpick 0",
    ]
    return "\n".join(lines)


def preset_lines(presets: Iterable[ConsoleCommandPreset] | None = None) -> str:
    presets = list(presets or default_presets())
    return "\n".join(p.line() for p in presets)
