from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from app.core.console_commands import build_console_command


MAGIC_ADD_KINDS = {"Spells", "Powers", "Abilities", "Active Effects", "Powers / Abilities"}
MAGIC_SHOUT_KIND = "Shouts"
MagicScriptMode = Literal["add_only", "match"]


@dataclass(slots=True)
class MagicCheckboxAction:
    """A queued desired-state change from the Magic checkboxes.

    Safe magic editing is intentionally implemented as Skyrim console batch
    generation, not direct ESS mutation.  Skyrim then owns the record creation,
    actor data updates, quest scripts, and shout-word side effects, which avoids
    the save corruption seen from raw learned-list patching.
    """

    kind: str
    name: str
    editor_id: str
    form_id: str
    desired_unlocked: bool
    currently_unlocked: bool
    favorite: bool = False
    source: str = ""
    direct_save_supported: bool = True

    @property
    def action_label(self) -> str:
        if self.desired_unlocked == self.currently_unlocked:
            return "No change"
        return "Unlock/Add" if self.desired_unlocked else "Remove/Lock"

    def command_lines(self) -> list[str]:
        form_id = (self.form_id or "").strip()
        if not form_id:
            return []
        if self.kind == MAGIC_SHOUT_KIND:
            if self.desired_unlocked:
                # Shout rows are Word of Power IDs in this tool.  Skyrim's own
                # commands safely create/update the related word/shout state.
                return [
                    build_console_command("player.teachword", form_id, None),
                    build_console_command("player.unlockword", form_id, None),
                ]
            # Skyrim has no stable console equivalent for un-teaching a word.
            return []
        if self.kind in MAGIC_ADD_KINDS:
            command = "player.addspell" if self.desired_unlocked else "player.removespell"
            return [build_console_command(command, form_id, None)]
        return []

    def unsupported_reason(self, mode: MagicScriptMode = "match") -> str:
        if self.desired_unlocked == self.currently_unlocked:
            return ""
        if mode == "add_only" and not self.desired_unlocked:
            return "Skipped in Safe Add/Unlock Only mode; this mode never removes spells, powers, abilities, or shout words."
        if self.kind == MAGIC_SHOUT_KIND and not self.desired_unlocked:
            return "Console-script removal of shout words is not safely supported."
        if self.kind not in MAGIC_ADD_KINDS and self.kind != MAGIC_SHOUT_KIND:
            return f"Unsupported magic kind: {self.kind}"
        return ""


def _action_title(action: MagicCheckboxAction) -> str:
    return action.name or action.editor_id or action.form_id


def build_magic_command_script(actions: Iterable[MagicCheckboxAction], mode: MagicScriptMode = "add_only") -> str:
    """Build a Skyrim console batch file for queued magic checkbox actions.

    mode="add_only" is the default safe workflow.  It emits only add/unlock
    commands and comments out removal requests.  mode="match" can also emit
    player.removespell for normal spells/powers/abilities, but shout removals
    still stay skipped because Skyrim has no safe unteachword command.
    """

    if mode not in {"add_only", "match"}:
        mode = "add_only"
    actions = [a for a in actions if a.desired_unlocked != a.currently_unlocked]
    mode_label = "Safe Add/Unlock Only" if mode == "add_only" else "Match Checkboxes"
    lines: list[str] = [
        "; Skyrim Save Lab safe magic script",
        f"; Mode: {mode_label}",
        "; This does NOT edit the save file directly.",
        "; Put this .txt beside SkyrimSE.exe/TESV.exe or another location your console 'bat' command can read.",
        "; In Skyrim, open the console and run: bat skyrim_magic_changes",
        "; After it finishes, wait a few seconds, open the magic menu, then make a new in-game save.",
        "",
    ]
    if not actions:
        lines.append("; No magic checkbox changes are currently queued.")
        return "\n".join(lines) + "\n"

    emitted = 0
    skipped: list[tuple[MagicCheckboxAction, str]] = []
    for action in actions:
        reason = action.unsupported_reason(mode)
        if reason:
            skipped.append((action, reason))
            continue
        commands = action.command_lines()
        title = _action_title(action)
        if commands:
            lines.append(f"; {action.action_label}: {title} [{action.kind}] {action.form_id}")
            lines.extend(commands)
            lines.append("")
            emitted += len(commands)
        else:
            skipped.append((action, "No safe command is available."))

    if skipped:
        lines.append("; Skipped requests")
        for action, reason in skipped:
            title = _action_title(action)
            lines.append(f"; - {title} [{action.kind}] {action.form_id}: {reason}")
        lines.append("")

    if emitted == 0:
        lines.append("; No runnable commands were emitted for the current mode.")
    lines.append("; End of Skyrim Save Lab safe magic script")
    return "\n".join(lines).rstrip() + "\n"
