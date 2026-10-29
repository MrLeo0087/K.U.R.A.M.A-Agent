"""files: list, find, read, write, move, copy, delete (asks first), make folders, organize, convert, lock. Safe
dispatcher; the specialised file tools keep their own confirmations."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

TABLE = {
    "list": Act("list_folder", lambda a: {"path": a.get("path") or a.get("query") or "~", "pattern": a.get("text", "")}),
    "find": Act("find_files", lambda a: {"query": a.get("query") or a.get("path"), "path": a.get("path") if a.get("query") else "",
                                         "kind": a.get("text", "any")}),
    "read": Act("read_text", lambda a: {"source": "file", "path": a.get("path")}),
    "write": Act("write_file", lambda a: {"path": a.get("path"), "content": a.get("text", "")}),
    "mkdir": Act("make_folder", lambda a: {"path": a.get("path")}),
    "move": Act("move_path", lambda a: {"source": a.get("path"), "destination": a.get("to")}),
    "copy": Act("copy_path", lambda a: {"source": a.get("path"), "destination": a.get("to")}),
    "delete": Act("delete_to_trash", lambda a: {"path": a.get("path")}),
    "organize": Act("organize_files", lambda a: {"action": a.get("text", "organize"), "folder": a.get("path", "~/Downloads")}),
    "convert": Act("convert_file", lambda a: {"path": a.get("path"), "to": a.get("to")}),
    "lock": Act("folder_lock", lambda a: {"action": a.get("text", "lock"), "path": a.get("path")}),
}


@tool(group="core", safety="safe",
      description="Files and folders anywhere on the laptop: list a folder, find files by their NAME (not code inside them), read, write (NEW files; to change code in a file open in VS Code use text edit_code), make a "
                  "folder, move, copy, delete (to trash, asks first), organize a messy folder, convert a file, lock a folder.")
def files(action: Literal["list", "find", "read", "write", "mkdir", "move", "copy", "delete", "organize", "convert", "lock"],
          path: str = "", query: str = "", to: str = "", text: str = "") -> str:
    """Files and folders.

    Args:
        action: list, find, read, write, mkdir, move, copy, delete, organize, convert, lock.
        path: The file or folder; loose names work ('downloads', 'project1 then tara').
        query: For find: the file name or part of it ('main.py', 'naruto'), searched on all disks.
        to: Destination folder (move/copy) or format (convert: pdf, md, mp3...).
        text: write: the content; find: name/folder/content; organize: organize/apply/undo; lock: lock/unlock.
    """
    return run(TABLE, {"action": action, "path": path, "query": query, "to": to, "text": text})
