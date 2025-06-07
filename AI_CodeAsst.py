#!/usr/bin/env python3

import os
import sys
import json
from pathlib import Path
from textwrap import dedent
from typing import List, Dict, Any, Optional, Tuple
import shutil # For copying .ai_ignore_example

# Third-party libraries
import litellm
from litellm import completion, acompletion # For async if we need it later
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.style import Style
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.prompt import Prompt, Confirm
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style as PromptStyle
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
import time
import uuid # For unique tool call IDs if needed

# --- Configuration ---
CONFIG_DIR = Path.home() / ".ai_code_assistant"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSION_DIR = CONFIG_DIR / "sessions"
DEFAULT_AI_IGNORE_FILE = ".ai_ignore"
AI_IGNORE_EXAMPLE_FILE = CONFIG_DIR / ".ai_ignore_example"

# Initialize Rich console
console = Console()

# Initialize prompt_toolkit session
try:
    prompt_session = PromptSession(
        history=FileHistory(CONFIG_DIR / ".prompt_history"),
        auto_suggest=AutoSuggestFromHistory(),
        style=PromptStyle.from_dict({
            'prompt': '#00aaff bold',  # Light blue prompt
            'completion-menu.completion': 'bg:#1e3a8a fg:#ffffff',
            'completion-menu.completion.current': 'bg:#3b82f6 fg:#ffffff bold',
        })
    )
except Exception: # Fallback if FileHistory path is not writable initially
    prompt_session = PromptSession(
        style=PromptStyle.from_dict({
            'prompt': '#00aaff bold',
        })
    )


# --- Global State & Configuration Variables ---
conversation_history: List[Dict[str, Any]] = []
current_llm_model: str = "gpt-4.1" # Default model
current_workspace_root: Optional[Path] = None
# litellm.set_verbose = True # For debugging LiteLLM calls

# --------------------------------------------------------------------------------
# 1. Pydantic Schemas (no changes needed from original for these)
# --------------------------------------------------------------------------------
class FileToCreate(BaseModel):
    path: str
    content: str

class FileToEdit(BaseModel):
    path: str
    original_snippet: str # This should be the exact snippet the LLM intends to replace
    new_snippet: str

# --------------------------------------------------------------------------------
# 2. Function Calling Tool Definitions
# --------------------------------------------------------------------------------
# These definitions are standard and should work with most models via LiteLLM
tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a single file from the filesystem. Always use this before attempting to edit a file to get its current content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read (relative to workspace root or absolute).",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_multiple_files",
            "description": "Read the content of multiple files from the filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of file paths to read (relative to workspace root or absolute).",
                    }
                },
                "required": ["file_paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file or overwrite an existing file with the provided content. Ensure the path is correct and the content is complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path where the file should be created (relative to workspace root or absolute).",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full content to write to the file.",
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_multiple_files",
            "description": "Create multiple files at once. Useful for generating a set of related files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "File path (relative to workspace root or absolute)."},
                                "content": {"type": "string", "description": "Full file content."},
                            },
                            "required": ["path", "content"],
                        },
                        "description": "Array of files to create with their paths and content.",
                    }
                },
                "required": ["files"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file by replacing a specific snippet of its current content with new content. CRITICAL: You MUST use 'read_file' on the target file in a previous step within the current turn to get the exact 'original_snippet' to replace. Do not guess the snippet. If the snippet is not found or is ambiguous, the edit will fail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to edit (relative to workspace root or absolute).",
                    },
                    "original_snippet": {
                        "type": "string",
                        "description": "The exact, verbatim text snippet from the current file content to find and replace. This MUST be obtained by reading the file first.",
                    },
                    "new_snippet": {
                        "type": "string",
                        "description": "The new text to replace the original snippet with.",
                    },
                },
                "required": ["file_path", "original_snippet", "new_snippet"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory_contents",
            "description": "List files and subdirectories within a specified directory. Helps in understanding project structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "The path to the directory to inspect (relative to workspace root or absolute). Defaults to current workspace root if not provided.",
                    }
                },
                "required": [], # directory_path is optional
            },
        },
    }
]

# --------------------------------------------------------------------------------
# 3. System Prompt
# --------------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = dedent("""\
    You are an elite AI Software Engineer. Your goal is to assist the user with software development tasks by understanding their requests, interacting with their file system (via provided tools), and generating code or explanations.

    Current Model: {model_name}
    Workspace Root: {workspace_root_info}

    Core Capabilities:
    1. Code Analysis & Discussion: Analyze code, explain concepts, suggest optimizations, debug.
    2. File Operations (via function calls):
        - read_file: Read a single file. CRITICAL: Always read a file before attempting to edit it to get the exact current content for `original_snippet`.
        - read_multiple_files: Read multiple files.
        - create_file: Create/overwrite a file.
        - create_multiple_files: Create multiple files.
        - edit_file: Make precise edits. You MUST provide an `original_snippet` that exactly matches a part of the current file content. Get this snippet by calling `read_file` first.
        - list_directory_contents: List files and folders in a directory.

    Guidelines:
    1. Clarification: If a request is ambiguous, ask for clarification.
    2. Tool Usage:
        - Use tools when necessary to interact with the file system.
        - Announce your intention to use a tool before making the call. For example: "I will now read the file `main.py` to understand its current structure."
        - For `edit_file`, it is MANDATORY to first call `read_file` on the target file in the same turn or ensure its content is already in the recent conversation. The `original_snippet` must be an exact match from the file's current content. Do not invent or assume snippets.
        - If an edit involves multiple changes or is complex, consider creating a new file with the full modified content instead of multiple `edit_file` calls, or explain the changes and ask the user to apply them.
    3. File Paths: When specifying file paths for tools, prefer paths relative to the workspace root if one is set. Otherwise, use paths as provided by the user or absolute paths if necessary.
    4. Responses: Provide clear, concise, and accurate responses. Explain your reasoning, especially for complex changes or tool usage.
    5. Safety: Be cautious with file modifications. If a user asks for a destructive operation, confirm their intent if it seems risky.
    6. Efficiency: If you need to perform multiple file operations, try to batch them if appropriate (e.g., using `read_multiple_files` or `create_multiple_files`).
    7. Context Awareness: Pay attention to the files already discussed or read in the current conversation.

    IMPORTANT: When you decide to use a tool, make the tool call. If your response requires a tool call, structure your response to make that call. Do not just describe the call you would make.
    If you are asked to edit a file, and you haven't read it recently, your first step should be to call `read_file`.

    Example for editing:
    User: "Change the greeting in `hello.py` to 'Aloha'."
    Assistant: "Okay, I'll change the greeting in `hello.py`. First, I need to read the file to see its current content.
    {{tool_call: read_file, arguments: {{"file_path": "hello.py"}}}}"
    Tool Response: "Content of file 'hello.py':\n\ndef greet():\n    print('Hello, world!')"
    Assistant: "Thanks! Now I see the content. I will replace 'Hello, world!' with 'Aloha'.
    {{tool_call: edit_file, arguments: {{"file_path": "hello.py", "original_snippet": "Hello, world!", "new_snippet": "Aloha"}}}}"
""")

def get_system_prompt() -> str:
    global current_llm_model, current_workspace_root
    workspace_info = str(current_workspace_root) if current_workspace_root else "Not set. Paths will be resolved from the current working directory or absolute paths."
    return SYSTEM_PROMPT_TEMPLATE.format(model_name=current_llm_model, workspace_root_info=workspace_info)

# --------------------------------------------------------------------------------
# 4. Configuration Management (New Feature)
# --------------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "default_model": "gpt-4o-mini", # A common, capable default
    "api_keys": {
        "openai": "YOUR_OPENAI_API_KEY_HERE_OR_SET_ENV_VAR",
        # Add other providers as needed, or rely purely on environment variables
    },
    "profiles": {
        "default": {
            "model": "gpt-4o-mini",
            "workspace_root": None,
            "auto_add_paths": [],
            "custom_ai_ignore": None, # Path to a custom .ai_ignore file for this profile
        }
    },
    "current_profile": "default",
    "max_tokens_response": 8000, # Max tokens for LLM response
    "max_tokens_context": 120000, # Approximate context window, LiteLLM handles specifics
}

def ensure_config_defaults(config: Dict) -> Dict:
    """Ensure all default keys exist in the loaded config."""
    updated = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
            updated = True
        elif isinstance(value, dict): # For nested dicts like profiles
            for sub_key, sub_value in value.items():
                if key == "profiles" and sub_key not in config[key]: # Ensure default profile exists
                     config[key][sub_key] = sub_value
                     updated = True
                elif isinstance(sub_value, dict) and config[key].get(sub_key) and isinstance(config[key][sub_key], dict):
                     for s_sub_key, s_sub_value in sub_value.items():
                        if s_sub_key not in config[key][sub_key]:
                            config[key][sub_key][s_sub_key] = s_sub_value
                            updated = True
    if "max_tokens_response" not in config:
        config["max_tokens_response"] = DEFAULT_CONFIG["max_tokens_response"]
        updated = True
    if "max_tokens_context" not in config:
        config["max_tokens_context"] = DEFAULT_CONFIG["max_tokens_context"]
        updated = True
    return config


def load_config() -> Dict:
    global current_llm_model, current_workspace_root
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # Create example .ai_ignore if it doesn't exist
    if not AI_IGNORE_EXAMPLE_FILE.exists():
        try:
            with open(AI_IGNORE_EXAMPLE_FILE, "w") as f:
                f.write(dedent("""\
                    # Lines starting with # are comments.
                    # Blank lines are ignored.
                    # File and directory names to ignore.
                    # Wildcards are not yet supported in this basic example, but can be added.
                    node_modules/
                    .git/
                    __pycache__/
                    *.pyc
                    *.tmp
                    .DS_Store
                    # Sensitive files
                    *.env
                    secrets.txt
                """))
            console.print(f"Created example ignore file at [cyan]{AI_IGNORE_EXAMPLE_FILE}[/cyan]", style="dim")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not create example ignore file: {e}[/yellow]", style="dim")


    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                config_data = json.load(f)
            config_data = ensure_config_defaults(config_data) # Ensure all keys are present
        except json.JSONDecodeError:
            console.print(f"[yellow]Warning: config.json is corrupted. Loading defaults.[/yellow]")
            config_data = DEFAULT_CONFIG.copy()
        except Exception as e:
            console.print(f"[red]Error loading config: {e}. Loading defaults.[/red]")
            config_data = DEFAULT_CONFIG.copy()
    else:
        console.print(f"Config file not found at [cyan]{CONFIG_FILE}[/cyan]. Creating with defaults.", style="blue")
        config_data = DEFAULT_CONFIG.copy()

    save_config(config_data) # Save to ensure it's written if created or updated

    # Apply current profile settings
    profile_name = config_data.get("current_profile", "default")
    profile = config_data.get("profiles", {}).get(profile_name, DEFAULT_CONFIG["profiles"]["default"])

    current_llm_model = profile.get("model", config_data.get("default_model", "gpt-4.1"))
    ws_root_str = profile.get("workspace_root")
    if ws_root_str:
        current_workspace_root = Path(ws_root_str).resolve()
        if not current_workspace_root.is_dir():
            console.print(f"[yellow]Warning: Workspace root '{current_workspace_root}' in profile '{profile_name}' is not a valid directory. Ignoring.[/yellow]")
            current_workspace_root = None
    else:
        current_workspace_root = None

    # Set LiteLLM API keys from config if present, otherwise env vars are used by LiteLLM
    # LiteLLM automatically picks up OPENAI_API_KEY, ANTHROPIC_API_KEY etc. from env.
    # This section is if you want to manage them explicitly via config.json (less secure).
    # For simplicity and security, relying on environment variables is often better.
    # Example: if "openai" in config_data.get("api_keys", {}):
    #    os.environ["OPENAI_API_KEY"] = config_data["api_keys"]["openai"]

    # Auto-add paths from profile
    auto_add_paths = profile.get("auto_add_paths", [])
    if auto_add_paths:
        console.print(f"Auto-adding paths from profile '{profile_name}':", style="blue")
        for path_str in auto_add_paths:
            handle_add_command_logic(path_str, is_auto_add=True)

    return config_data

def save_config(config_data: Dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_data, f, indent=4)
    except Exception as e:
        console.print(f"[red]Error saving config: {e}[/red]")

# --- Initialize config on load ---
config = load_config()


# --------------------------------------------------------------------------------
# 5. Helper Functions (File Ops, Path Normalization, etc.)
# --------------------------------------------------------------------------------
def normalize_path_str(path_str: str) -> str:
    """Return a canonical, absolute version of the path string, resolved against workspace root if set."""
    global current_workspace_root

    # Expand ~ to user's home directory
    expanded_path = Path(path_str).expanduser()

    if current_workspace_root:
        # If path is already absolute, use it. Otherwise, join with workspace root.
        resolved_path = current_workspace_root / expanded_path if not expanded_path.is_absolute() else expanded_path
    else:
        # If no workspace root, resolve relative to CWD or use absolute path
        resolved_path = Path.cwd() / expanded_path if not expanded_path.is_absolute() else expanded_path

    try:
        # .resolve(strict=False) handles non-existent paths for creation, but strict=True ensures it exists for reading/editing
        # For our purpose, we often deal with paths that might be created, so strict=False is okay for normalization.
        # However, actual file operations should handle FileNotFoundError.
        final_path = resolved_path.resolve(strict=False)
    except Exception as e: # Catch potential errors during resolution (e.g. permission issues)
        console.print(f"[yellow]Warning: Could not fully resolve path '{path_str}': {e}. Using as is: {resolved_path}[/yellow]")
        final_path = resolved_path # Fallback to non-strictly resolved

    # Security check: prevent escaping the workspace root if one is set
    if current_workspace_root:
        try:
            final_path.relative_to(current_workspace_root)
        except ValueError:
            # Path is outside the workspace root. This could be intentional for absolute paths.
            # For now, we allow it but one might want to restrict this.
            pass # Allow absolute paths or paths outside if explicitly given

    if ".." in str(final_path): # A basic check, Path.resolve() should handle most traversals
        # This check might be overly simplistic if ".." is part of a legitimate filename.
        # Path.is_relative_to (Python 3.9+) is better if available and applicable.
        pass

    return str(final_path)


def read_local_file(file_path_str: str) -> str:
    normalized_path = normalize_path_str(file_path_str)
    try:
        with open(normalized_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {normalized_path}")
    except Exception as e:
        raise OSError(f"Error reading file {normalized_path}: {e}")

def create_local_file(path_str: str, content: str):
    file_path = Path(normalize_path_str(path_str))

    # Basic security: prevent writing to very high-level system dirs (very basic check)
    # A more robust check would involve allowlists or more sophisticated sandboxing.
    if file_path.is_absolute() and len(file_path.parts) < 3 and os.name != 'nt': # e.g. /bin, /etc
         if not Confirm.ask(f"[yellow]⚠️ You are about to write to a sensitive system path: [bold red]{file_path}[/bold red]. Are you absolutely sure?[/yellow]", default=False):
            console.print("[bold red]Operation cancelled by user.[/bold red]")
            raise PermissionError(f"User cancelled writing to sensitive path: {file_path}")

    if len(content) > 10_000_000:  # 10MB limit for safety
        raise ValueError("File content exceeds 10MB size limit.")

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    console.print(f"[bold green]✓[/bold green] Created/updated file: '[bright_cyan]{file_path}[/bright_cyan]'")

def apply_local_diff_edit(path_str: str, original_snippet: str, new_snippet: str):
    normalized_path = normalize_path_str(path_str)
    try:
        content = read_local_file(normalized_path)

        occurrences = content.count(original_snippet)
        if occurrences == 0:
            console.print(f"[bold red]✗ Original snippet not found in '{normalized_path}'.[/bold red]")
            console.print("Expected snippet (verbatim):")
            console.print(Panel(original_snippet, title="Expected Snippet", border_style="red", expand=False))
            # console.print("Actual file content (first 500 chars):")
            # console.print(Panel(content[:500] + "..." if len(content) > 500 else content, title="Actual Content (Preview)", border_style="yellow", expand=False))
            raise ValueError("Original snippet not found. File not changed.")

        if occurrences > 1:
            # For now, we'll just replace the first one as per str.replace behavior.
            # A more advanced version could ask the user or use line numbers.
            console.print(f"[yellow]⚠ Warning: Original snippet found {occurrences} times in '{normalized_path}'. Replacing the first one.[/yellow]")
            # Could add interactive selection here in the future.

        updated_content = content.replace(original_snippet, new_snippet, 1)

        if updated_content == content: # No change made
            console.print(f"[yellow]⚠ Snippet replacement resulted in no change to the file '{normalized_path}'. This might happen if the new_snippet is identical to original_snippet or if the snippet was not actually found by str.replace (should be caught by occurrences check).[/yellow]")
            # This case should ideally be caught by `occurrences == 0` or if `original_snippet == new_snippet`.
            # If it still happens, it's an anomaly.
            return # Do not rewrite if no change.

        create_local_file(normalized_path, updated_content)
        console.print(f"[bold green]✓[/bold green] Applied edit to '[bright_cyan]{normalized_path}[/bright_cyan]'")

    except FileNotFoundError:
        console.print(f"[bold red]✗[/bold red] File not found for editing: '[bright_cyan]{normalized_path}[/bright_cyan]'")
        raise
    except ValueError as e:
        console.print(f"[bold red]✗[/bold red] {str(e)}")
        raise
    except Exception as e:
        console.print(f"[bold red]✗[/bold red] Error applying edit to '{normalized_path}': {e}")
        raise

def is_binary_file(file_path_str: str, peek_size: int = 1024) -> bool:
    try:
        with open(normalize_path_str(file_path_str), 'rb') as f:
            chunk = f.read(peek_size)
        return b'\0' in chunk
    except Exception:
        return True # Treat as binary if error reading

def get_ai_ignore_patterns(profile_custom_ignore_path: Optional[str]) -> List[str]:
    """Loads ignore patterns from global .ai_ignore and profile-specific one if provided."""
    patterns = []
    # Default ignore file in CWD
    default_ignore = Path(DEFAULT_AI_IGNORE_FILE)
    # User-wide example/default ignore file
    user_wide_ignore = AI_IGNORE_EXAMPLE_FILE

    files_to_check = []
    if default_ignore.exists():
        files_to_check.append(default_ignore)
    elif user_wide_ignore.exists() and not profile_custom_ignore_path : # Use user-wide if no local and no profile specific
        files_to_check.append(user_wide_ignore)

    if profile_custom_ignore_path:
        profile_ignore_path = Path(normalize_path_str(profile_custom_ignore_path))
        if profile_ignore_path.exists():
            files_to_check.append(profile_ignore_path)
        else:
            console.print(f"[yellow]Profile custom ignore file not found: {profile_ignore_path}[/yellow]", style="dim")

    if not files_to_check:
        console.print(f"No .ai_ignore file found in CWD, profile, or user config dir ([cyan]{user_wide_ignore}[/cyan]).", style="dim")


    for file_path in files_to_check:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped_line = line.strip()
                    if stripped_line and not stripped_line.startswith("#"):
                        patterns.append(stripped_line)
            console.print(f"Loaded ignore patterns from [cyan]{file_path}[/cyan]", style="dim")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not read ignore file {file_path}: {e}[/yellow]", style="dim")
    return list(set(patterns)) # Unique patterns

def path_matches_ignore(path: Path, ignore_patterns: List[str], root_dir: Path) -> bool:
    """Check if a path matches any ignore pattern. Basic implementation."""
    # Ensure path is relative to the root_dir for pattern matching
    try:
        relative_path_str = str(path.relative_to(root_dir))
    except ValueError: # path is not under root_dir, should not happen if called correctly
        relative_path_str = str(path)

    for pattern in ignore_patterns:
        # Simple matching:
        # If pattern ends with /, it's a directory pattern
        if pattern.endswith('/'):
            dir_pattern = pattern.rstrip('/')
            # Check if any part of the path matches the directory pattern
            # e.g., pattern "node_modules/" should match "node_modules/some_file.js"
            # or "src/node_modules/file.js"
            if f"/{dir_pattern}/" in f"/{relative_path_str}" or relative_path_str.startswith(dir_pattern + "/"):
                 return True
        # Exact file/dir name match
        elif pattern == path.name: # Match file/dir name directly
            return True
        # Wildcard for extension (e.g., *.pyc)
        elif pattern.startswith("*."):
            ext = pattern[1:] # .pyc
            if path.name.endswith(ext):
                return True
        # Direct path match (e.g., specific_folder/specific_file.txt)
        elif pattern == relative_path_str:
            return True
    return False


def add_directory_to_conversation(directory_path_str: str, ignore_patterns: List[str]):
    global conversation_history
    normalized_dir_path = Path(normalize_path_str(directory_path_str))

    if not normalized_dir_path.is_dir():
        console.print(f"[red]Error: '{normalized_dir_path}' is not a valid directory.[/red]")
        return

    console.print(f"Scanning directory: [cyan]{normalized_dir_path}[/cyan]...")

    # Hardcoded common exclusions (less critical now with .ai_ignore)
    # These can be moved to the default .ai_ignore_example
    excluded_dirs_hardcoded = {".git", "__pycache__", "node_modules", ".venv", "venv", ".vscode", ".idea"}
    excluded_extensions_hardcoded = {
        ".pyc", ".pyo", ".pyd", ".so", ".o", ".a", ".dll", ".exe", # Compiled
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp", ".svg", # Images
        ".mp3", ".wav", ".ogg", ".mp4", ".avi", ".mov", ".webm", # Media
        ".zip", ".tar", ".gz", ".rar", ".7z", # Archives
        ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", # Documents
        ".log", ".tmp", ".temp", ".bak", ".swp", # Logs & temp
        ".db", ".sqlite", ".sqlite3" # Databases
    }

    added_files_count = 0
    skipped_files_info = [] # Store (path, reason)

    # Use normalized_dir_path as the root for pattern matching
    scan_root_dir = normalized_dir_path

    for item in normalized_dir_path.rglob("*"): # Recursive glob
        if item.is_file():
            # Check hardcoded dir exclusions first (for parent dirs)
            if any(excluded_dir in item.parts for excluded_dir in excluded_dirs_hardcoded):
                skipped_files_info.append((str(item), "Parent in hardcoded excluded dirs"))
                continue
            if item.name in excluded_dirs_hardcoded: # If file itself is named like an excluded dir (unlikely but possible)
                 skipped_files_info.append((str(item), "In hardcoded excluded files/dirs"))
                 continue

            # Check .ai_ignore patterns
            if path_matches_ignore(item, ignore_patterns, scan_root_dir):
                skipped_files_info.append((str(item), "Matches .ai_ignore pattern"))
                continue

            if item.suffix.lower() in excluded_extensions_hardcoded:
                skipped_files_info.append((str(item), f"Hardcoded excluded extension ({item.suffix})"))
                continue

            if is_binary_file(str(item)):
                skipped_files_info.append((str(item), "Binary file"))
                continue

            try:
                if item.stat().st_size > 5_000_000: # 5MB limit per file
                    skipped_files_info.append((str(item), "Exceeds 5MB size limit"))
                    continue

                content = read_local_file(str(item))
                # Add to conversation history (ensure it's not already there)
                file_marker_content = f"Content of file '{str(item)}':\n\n{content}"
                if not any(msg.get("role") == "system" and msg.get("content","").startswith(f"Content of file '{str(item)}':") for msg in conversation_history):
                    conversation_history.append({"role": "system", "content": file_marker_content, "type": "file_context", "path": str(item)})
                    added_files_count += 1
                else:
                    skipped_files_info.append((str(item), "Already in context"))


            except Exception as e:
                skipped_files_info.append((str(item), f"Error reading: {e}"))
        elif item.is_dir(): # For directories, check if they match ignore patterns to skip scanning them
            if any(excluded_dir in item.parts for excluded_dir in excluded_dirs_hardcoded) or \
               path_matches_ignore(item, ignore_patterns, scan_root_dir) or \
               item.name in excluded_dirs_hardcoded:
                # If a directory is ignored, rglob won't enter it if we could prune it.
                # However, rglob yields all items then we filter.
                # For more efficient skipping, os.walk would be better to prune DIRS.
                # For now, this just means files within it will be skipped individually.
                pass


    console.print(f"[green]✓[/green] Added {added_files_count} new files from '[cyan]{normalized_dir_path}[/cyan]' to conversation context.")
    if skipped_files_info:
        console.print(f"[yellow]Skipped {len(skipped_files_info)} files/items.[/yellow] (Use /list_skipped for details)")
        # Store skipped files info for potential review by user, e.g. via a new command /list_skipped_files
        # For now, just print a summary or first few.
        if any(s[1] == "Matches .ai_ignore pattern" for s in skipped_files_info):
             console.print(f"[dim]Some files were skipped due to '.ai_ignore' patterns.[/dim]")


# --------------------------------------------------------------------------------
# 6. Conversation History Management (Context Trimming, Adding files)
# --------------------------------------------------------------------------------
def trim_conversation_history():
    """Trim conversation history to prevent token limit issues."""
    global conversation_history, config
    # A more sophisticated trimming would estimate token count.
    # For now, simple message count based, preserving system prompt and recent messages.
    # LiteLLM can also do its own context window management.

    max_messages = 30 # Keep last N user/assistant messages + system prompts + file contexts

    system_prompts = [msg for msg in conversation_history if msg["role"] == "system" and msg.get("type") != "file_context"]
    file_contexts = [msg for msg in conversation_history if msg.get("type") == "file_context"]

    # User and assistant messages, excluding tool responses for this count
    # Tool responses are tightly coupled with their preceding assistant message and subsequent assistant message.
    # A better trimming would keep tool_call -> tool_response -> assistant_response blocks together.

    # Let's try a simpler approach: keep system prompt, all file contexts, and last N other messages.
    # This might still exceed token limits if file contexts are huge.

    other_messages = [msg for msg in conversation_history if msg.get("type") != "file_context" and msg["role"] != "system"]

    if len(other_messages) > max_messages:
        other_messages_to_keep = other_messages[-max_messages:]
    else:
        other_messages_to_keep = other_messages

    # Rebuild, ensuring system prompt is first.
    new_history = []
    if system_prompts: # Should always be at least one (the main system prompt)
        new_history.append(system_prompts[0]) # Main system prompt
    new_history.extend(file_contexts) # Add all file contexts
    new_history.extend(other_messages_to_keep) # Add recent interactions

    # Add any other system prompts (e.g., loaded file content that wasn't marked as file_context type)
    # This part might be tricky if "system" role is used for other things.
    # The current `add_directory_to_conversation` marks them with type "file_context".

    if len(conversation_history) > len(new_history):
        console.print(f"[dim]Trimmed conversation history from {len(conversation_history)} to {len(new_history)} messages.[/dim]")

    conversation_history = new_history


def ensure_file_in_context(file_path_str: str) -> bool:
    """Adds file to context if not already present. Returns True if successful/already there."""
    global conversation_history
    normalized_path = normalize_path_str(file_path_str)

    # Check if file content is already in history
    # This check needs to be robust. Comparing full content string might be too much.
    # We'll check for the specific marker.
    file_marker_prefix = f"Content of file '{normalized_path}':"
    if any(msg.get("role") == "system" and msg.get("content","").startswith(file_marker_prefix) for msg in conversation_history):
        return True # Already in context

    try:
        content = read_local_file(normalized_path)
        conversation_history.append({
            "role": "system",
            "content": f"{file_marker_prefix}\n\n{content}",
            "type": "file_context", # Mark it for easier management
            "path": normalized_path
        })
        console.print(f"[dim]Added file '{normalized_path}' to context for operation.[/dim]")
        return True
    except Exception as e:
        console.print(f"[red]✗[/red] Could not read file '[cyan]{normalized_path}[/cyan]' to add to context: {e}")
        return False

# --------------------------------------------------------------------------------
# 7. LLM Interaction with LiteLLM and Function Calling
# --------------------------------------------------------------------------------
def execute_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    """Executes a single tool call and returns a message for conversation history."""
    tool_call_id = tool_call.get("id", f"call_{uuid.uuid4().hex[:8]}") # Ensure there's an ID
    function_call_details = tool_call.get("function")

    if not function_call_details:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": "unknown_function_structure",
            "content": "Error: Malformed tool call, missing 'function' details.",
        }

    function_name = function_call_details.get("name")

    # Ensure arguments are parsed from string if necessary
    raw_arguments = function_call_details.get("arguments", "{}")
    try:
        if isinstance(raw_arguments, str):
            arguments = json.loads(raw_arguments)
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            raise ValueError("Arguments are not a valid JSON string or dict.")
    except json.JSONDecodeError as e:
        console.print(f"[red]Error decoding arguments for {function_name}: {e}[/red]")
        console.print(f"Raw arguments: {raw_arguments}")
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": function_name,
            "content": f"Error: Could not parse arguments for {function_name}. Invalid JSON: {e}. Arguments received: {raw_arguments}",
        }
    except ValueError as e: # Catches the custom ValueError
        console.print(f"[red]Error with arguments for {function_name}: {e}[/red]")
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": function_name,
            "content": f"Error: Invalid arguments structure for {function_name}: {e}. Arguments received: {raw_arguments}",
        }


    console.print(f"Attempting to execute tool: [bright_magenta]{function_name}[/bright_magenta] with args: [dim]{arguments}[/dim]")

    result_content = ""
    try:
        if function_name == "read_file":
            file_path = arguments["file_path"]
            # normalized_path = normalize_path_str(file_path) # read_local_file does this
            content = read_local_file(file_path) # Use original path, normalize inside
            result_content = f"Content of file '{normalize_path_str(file_path)}':\n\n{content}"

        elif function_name == "read_multiple_files":
            file_paths = arguments["file_paths"]
            results = []
            for fp_str in file_paths:
                try:
                    # normalized_fp = normalize_path_str(fp_str) # read_local_file does this
                    content = read_local_file(fp_str)
                    results.append(f"Content of file '{normalize_path_str(fp_str)}':\n\n{content}")
                except Exception as e:
                    results.append(f"Error reading '{normalize_path_str(fp_str)}': {e}")
            result_content = "\n\n" + "="*20 + " MULTIPLE FILE RESULTS " + "="*20 + "\n\n".join(results)

        elif function_name == "create_file":
            # Pydantic validation can be added here for more robustness
            file_to_create = FileToCreate(**arguments)
            create_local_file(file_to_create.path, file_to_create.content)
            result_content = f"Successfully created/updated file '{normalize_path_str(file_to_create.path)}'."

        elif function_name == "create_multiple_files":
            files_data = arguments["files"]
            created_files_paths = []
            for file_info_dict in files_data:
                file_to_create = FileToCreate(**file_info_dict)
                create_local_file(file_to_create.path, file_to_create.content)
                created_files_paths.append(normalize_path_str(file_to_create.path))
            result_content = f"Successfully created/updated {len(created_files_paths)} files: {', '.join(created_files_paths)}."

        elif function_name == "edit_file":
            file_to_edit = FileToEdit(**arguments)
            # CRITICAL: Ensure file is in context for the LLM to have based original_snippet on.
            # The LLM is prompted to call read_file first. This function ensures it again if needed.
            if not ensure_file_in_context(file_to_edit.path):
                 # If ensure_file_in_context fails, it prints an error.
                 # We should return an error message to the LLM.
                 raise ValueError(f"Could not ensure file '{file_to_edit.path}' was in context. Edit aborted.")

            apply_local_diff_edit(file_to_edit.path, file_to_edit.original_snippet, file_to_edit.new_snippet)
            result_content = f"Successfully applied edit to file '{normalize_path_str(file_to_edit.path)}'."
            # After edit, the context version of this file is stale.
            # We could re-add it, or let the LLM re-read if needed.
            # For now, remove the old context message.
            remove_file_from_context(normalize_path_str(file_to_edit.path), quiet=True)
            ensure_file_in_context(file_to_edit.path) # Add the new version

        elif function_name == "list_directory_contents":
            dir_path_str = arguments.get("directory_path") # Optional
            if dir_path_str:
                target_dir = Path(normalize_path_str(dir_path_str))
            elif current_workspace_root:
                target_dir = current_workspace_root
            else:
                target_dir = Path.cwd()

            if not target_dir.is_dir():
                raise ValueError(f"'{target_dir}' is not a valid directory.")

            items = []
            for item in target_dir.iterdir():
                item_type = "dir" if item.is_dir() else "file"
                items.append(f"- {item.name} ({item_type})")
            if not items:
                result_content = f"Directory '{target_dir}' is empty."
            else:
                result_content = f"Contents of directory '{target_dir}':\n" + "\n".join(items)

        else:
            result_content = f"Error: Unknown function '{function_name}'."
            console.print(f"[red]{result_content}[/red]")

    except FileNotFoundError as e:
        result_content = f"Error executing {function_name}: File not found. {e}"
        console.print(f"[red]{result_content}[/red]")
    except PermissionError as e:
        result_content = f"Error executing {function_name}: Permission denied. {e}"
        console.print(f"[red]{result_content}[/red]")
    except ValidationError as e: # Pydantic validation error
        result_content = f"Error executing {function_name}: Invalid arguments. {e.errors()}"
        console.print(f"[red]{result_content}[/red]")
    except KeyError as e: # Missing key in arguments
        result_content = f"Error executing {function_name}: Missing argument '{e}'. Arguments received: {arguments}"
        console.print(f"[red]{result_content}[/red]")
    except Exception as e:
        result_content = f"Error executing {function_name}: {type(e).__name__} - {e}"
        console.print(f"[red]{result_content}[/red]")
        # import traceback
        # console.print(f"[dim]{traceback.format_exc()}[/dim]")


    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": function_name, # LiteLLM expects 'name' here for the function that was called
        "content": result_content,
    }


def call_litellm_api(current_conversation: List[Dict[str, Any]], max_retries=2) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], Optional[List[Dict[str,Any]]]]:
    """
    Calls LiteLLM API.
    Returns (tool_calls_list, final_text_content, new_assistant_messages_for_history)
    """
    global current_llm_model, config

    console.print(f"\n[bold bright_blue]🤖 Assistant ({current_llm_model}) is thinking...[/bold bright_blue]")

    # DeepSeek specific 'reasoning_content' is not standard.
    # We'll just collect text and tool calls.
    full_response_text = ""
    accumulated_tool_calls: List[Dict[str, Any]] = [] # Correctly typed list of dicts

    # Prepare messages for LiteLLM, ensuring system prompt is up-to-date
    messages_for_api = [msg for msg in current_conversation if msg["role"] != "system"]
    messages_for_api.insert(0, {"role": "system", "content": get_system_prompt()})

    try:
        response = litellm.completion(
            model=current_llm_model,
            messages=messages_for_api,
            tools=tools,
            tool_choice="auto", # Let the model decide, or "any" for DeepSeek Coder models
            stream=True,
            # max_tokens=config.get("max_tokens_response", 8000) # Optional: LiteLLM might infer or use model defaults
        )

        # Variables to aggregate streamed tool call parts
        # LiteLLM streams tool calls piece by piece. We need to reconstruct them.
        # {index: {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}}
        tool_call_fragments: Dict[int, Dict[str, Any]] = {}

        for chunk in response:
            delta = chunk.choices[0].delta

            if delta.content:
                text_part = delta.content
                console.print(text_part, end="", style="bright_green")
                full_response_text += text_part

            if delta.tool_calls:
                for tool_call_chunk in delta.tool_calls:
                    index = tool_call_chunk.index

                    if index not in tool_call_fragments:
                        tool_call_fragments[index] = {
                            "id": None,
                            "type": "function",
                            "function": {"name": "", "arguments": ""}
                        }

                    current_fragment = tool_call_fragments[index]
                    if tool_call_chunk.id:
                        current_fragment["id"] = tool_call_chunk.id
                    if tool_call_chunk.function:
                        if tool_call_chunk.function.name:
                            current_fragment["function"]["name"] += tool_call_chunk.function.name
                        if tool_call_chunk.function.arguments:
                            current_fragment["function"]["arguments"] += tool_call_chunk.function.arguments

        console.print() # Newline after streaming assistant text

        # Finalize tool calls from fragments
        if tool_call_fragments:
            for _index, fragment in sorted(tool_call_fragments.items()): # Process in order
                if fragment["id"] and fragment["function"]["name"]: # Basic validation
                    accumulated_tool_calls.append({
                        "id": fragment["id"],
                        "type": fragment["type"],
                        "function": {
                            "name": fragment["function"]["name"],
                            "arguments": fragment["function"]["arguments"]
                        }
                    })

        # Construct the assistant message for history
        assistant_history_message: Dict[str, Any] = {"role": "assistant"}
        if full_response_text:
            assistant_history_message["content"] = full_response_text
        else: # Important for some models if only tool_calls are present
            assistant_history_message["content"] = None

        if accumulated_tool_calls:
            assistant_history_message["tool_calls"] = accumulated_tool_calls

        return accumulated_tool_calls, full_response_text, [assistant_history_message]

    except litellm.exceptions.APIConnectionError as e:
        console.print(f"\n[bold red]❌ LiteLLM API Connection Error: {e}[/bold red]")
    except litellm.exceptions.APIError as e: # Catch more generic LiteLLM API errors
        console.print(f"\n[bold red]❌ LiteLLM API Error: {e} (Model: {current_llm_model})[/bold red]")
    except litellm.exceptions.RateLimitError as e:
         console.print(f"\n[bold red]❌ LiteLLM Rate Limit Error: {e}[/bold red]")
    except litellm.exceptions.AuthenticationError as e:
        console.print(f"\n[bold red]❌ LiteLLM Authentication Error: {e}. Check your API key for {current_llm_model}.[/bold red]")
        console.print(f"[dim]LiteLLM expects API keys as environment variables (e.g., OPENAI_API_KEY, ANTHROPIC_API_KEY).[/dim]")
    except Exception as e:
        console.print(f"\n[bold red]❌ An unexpected error occurred during LiteLLM API call: {type(e).__name__} - {e}[/bold red]")
        # import traceback
        # console.print(f"[dim]{traceback.format_exc()}[/dim]")

    return None, None, None


def process_user_message(user_message: str):
    global conversation_history, config

    conversation_history.append({"role": "user", "content": user_message})
    trim_conversation_history()

    max_tool_iteration = 5 # Prevent infinite loops of tool calls
    current_tool_iteration = 0

    while current_tool_iteration < max_tool_iteration:
        current_tool_iteration += 1

        tool_calls_to_execute, assistant_text, new_hist_msgs = call_litellm_api(conversation_history)

        if new_hist_msgs:
            conversation_history.extend(new_hist_msgs)
        else: # API call failed critically
            break

        if not tool_calls_to_execute:
            # No tool calls, conversation ends here for this turn
            break

        # --- Interactive Tool Call Confirmation (New Feature) ---
        console.print(f"\n[bold yellow]🛠️ Assistant proposes to use {len(tool_calls_to_execute)} tool(s):[/bold yellow]")

        # Display proposed tool calls
        tool_table = Table(title="Proposed Tool Calls", show_lines=True, border_style="yellow")
        tool_table.add_column("#", style="dim")
        tool_table.add_column("Function", style="magenta")
        tool_table.add_column("Arguments", style="cyan")

        for i, tc in enumerate(tool_calls_to_execute):
            func_name = tc.get("function", {}).get("name", "N/A")
            args_str = tc.get("function", {}).get("arguments", "{}")
            try: # Pretty print JSON arguments
                args_pretty = json.dumps(json.loads(args_str), indent=2)
            except:
                args_pretty = args_str
            tool_table.add_row(str(i+1), func_name, args_pretty)
        console.print(tool_table)

        # Prompt for confirmation
        action = Prompt.ask(
            "[bold]Proceed with these tool calls?[/bold] (Yes/No/Edit/Skip)",
            choices=["y", "n", "e", "s", "yes", "no", "edit", "skip"],
            default="y"
        ).lower()

        if action.startswith("n") or action.startswith("s"):
            console.print("[bold red]Tool calls skipped by user.[/bold red]")
            # Add a message to history indicating skip, so LLM knows
            conversation_history.append({
                "role": "user", # Or a special "system" message
                "content": "User skipped the proposed tool calls. Please proceed without them or suggest alternatives."
            })
            # Break this loop and let the LLM respond again based on the skip.
            # This might mean we need another LLM call here. For now, just break.
            # A better flow would be to send this "skipped" message back to the LLM.
            # Let's try that:
            continue # This will trigger another call_litellm_api with the updated history.

        if action.startswith("e"):
            try:
                call_index_to_edit = int(Prompt.ask("Enter the number of the tool call to edit", default="1")) - 1
                if not (0 <= call_index_to_edit < len(tool_calls_to_execute)):
                    console.print("[red]Invalid number. Skipping edit.[/red]")
                else:
                    tc_to_edit = tool_calls_to_execute[call_index_to_edit]
                    console.print(f"Editing tool call: [magenta]{tc_to_edit['function']['name']}[/magenta]")
                    current_args_str = tc_to_edit['function']['arguments']
                    try:
                        current_args_dict = json.loads(current_args_str)
                    except json.JSONDecodeError:
                        console.print(f"[yellow]Warning: Arguments are not valid JSON. Editing as raw string.[/yellow]")
                        current_args_dict = None

                    if current_args_dict is not None:
                        edited_args_dict = {}
                        for key, value in current_args_dict.items():
                            new_val_str = Prompt.ask(f"Argument '{key}' (current: '{value}')", default=str(value))
                            # Try to parse back to original type if simple (int, bool), otherwise keep as string
                            try:
                                if isinstance(value, bool): edited_args_dict[key] = new_val_str.lower() in ['true', '1', 'yes']
                                elif isinstance(value, int): edited_args_dict[key] = int(new_val_str)
                                elif isinstance(value, float): edited_args_dict[key] = float(new_val_str)
                                else: edited_args_dict[key] = new_val_str
                            except ValueError:
                                edited_args_dict[key] = new_val_str # Keep as string if parse fails
                        tc_to_edit['function']['arguments'] = json.dumps(edited_args_dict)
                    else: # Edit as raw string
                         new_args_str = Prompt.ask(f"New arguments string (current: '{current_args_str}')", default=current_args_str)
                         tc_to_edit['function']['arguments'] = new_args_str
                    console.print("[green]Arguments updated.[/green]")
            except ValueError:
                console.print("[red]Invalid input for edit. Skipping edit.[/red]")
            # After edit, re-confirm or proceed. For now, assume proceed with edited calls.
            # The loop will continue, and these (potentially modified) tool_calls_to_execute will be used.

        # If 'yes' or after 'edit', proceed to execute
        tool_results = []
        console.print(f"\n[bold bright_cyan]⚡ Executing {len(tool_calls_to_execute)} function call(s)...[/bold bright_cyan]")
        for tool_call_data in tool_calls_to_execute:
            # Ensure tool_call_data has 'id' if it was generated by LiteLLM without one initially
            if "id" not in tool_call_data or not tool_call_data["id"]:
                tool_call_data["id"] = f"call_{uuid.uuid4().hex[:8]}"

            tool_response_message = execute_tool_call(tool_call_data)
            tool_results.append(tool_response_message)
            # Display tool result immediately
            console.print(f"  [dim]↳ Result for {tool_response_message['name']} (ID: {tool_response_message['tool_call_id']}):[/dim]")
            # Use Rich Markdown for potentially formatted content from tools
            console.print(Markdown(str(tool_response_message['content'])))


        conversation_history.extend(tool_results)
        trim_conversation_history()
        # Loop back to call LiteLLM again with tool results

    if current_tool_iteration >= max_tool_iteration:
        console.print("[bold yellow]⚠ Reached maximum tool iteration limit. Ending turn.[/bold yellow]")


# --------------------------------------------------------------------------------
# 8. Command Handling (New commands and modifications)
# --------------------------------------------------------------------------------
def handle_add_command_logic(path_to_add_str: str, is_auto_add: bool = False):
    """Logic for the /add command, callable by user and profile loading."""
    global conversation_history, config, current_workspace_root

    # Determine which .ai_ignore file to use
    current_profile_name = config.get("current_profile", "default")
    profile_settings = config.get("profiles", {}).get(current_profile_name, {})
    profile_ai_ignore = profile_settings.get("custom_ai_ignore")

    ignore_patterns = get_ai_ignore_patterns(profile_ai_ignore)

    normalized_path_to_add = Path(normalize_path_str(path_to_add_str))

    if normalized_path_to_add.is_dir():
        add_directory_to_conversation(str(normalized_path_to_add), ignore_patterns)
    elif normalized_path_to_add.is_file():
        try:
            if is_binary_file(str(normalized_path_to_add)):
                console.print(f"[yellow]Skipping binary file: {normalized_path_to_add}[/yellow]")
                return
            if normalized_path_to_add.stat().st_size > 5_000_000: # 5MB limit
                console.print(f"[yellow]Skipping file larger than 5MB: {normalized_path_to_add}[/yellow]")
                return

            # Add to conversation history (ensure it's not already there)
            file_marker_content_start = f"Content of file '{str(normalized_path_to_add)}':"
            if any(msg.get("role") == "system" and msg.get("content","").startswith(file_marker_content_start) for msg in conversation_history):
                if not is_auto_add: # Don't print if auto-adding, too verbose
                    console.print(f"[dim]File '[cyan]{normalized_path_to_add}[/cyan]' is already in context.[/dim]")
                return

            content = read_local_file(str(normalized_path_to_add))
            conversation_history.append({
                "role": "system",
                "content": f"{file_marker_content_start}\n\n{content}",
                "type": "file_context", # Mark for easier management
                "path": str(normalized_path_to_add)
            })
            if not is_auto_add:
                console.print(f"[bold green]✓[/bold green] Added file '[bright_cyan]{normalized_path_to_add}[/bright_cyan]' to conversation context.\n")
        except Exception as e:
            if not is_auto_add:
                console.print(f"[bold red]✗[/bold red] Could not add file '[cyan]{path_to_add_str}[/cyan]': {e}\n")
    else:
        if not is_auto_add:
            console.print(f"[red]Path not found or not a file/directory: {normalized_path_to_add}[/red]")


def try_handle_slash_command(user_input: str) -> bool:
    """Handles slash commands like /add, /model, /save, /load, etc."""
    global conversation_history, current_llm_model, config, current_workspace_root

    parts = user_input.lower().strip().split(maxsplit=2)
    command = parts[0]
    args = parts[1:] if len(parts) > 1 else []

    if command == "/add":
        if not args:
            console.print("[red]Usage: /add <file_or_directory_path>[/red]")
            return True
        path_to_add = user_input[len("/add "):].strip() # Get original case path
        handle_add_command_logic(path_to_add)
        return True

    elif command == "/setmodel":
        if not args:
            console.print(f"[red]Usage: /setmodel <model_name>[/red]. Current model: [cyan]{current_llm_model}[/cyan]")
            # Optionally list available models from LiteLLM or config here
            # console.print(f"Available models (example): {litellm.model_list}") # This can be slow
            return True
        new_model = args[0]
        # Basic validation: check if model string seems reasonable
        if not (new_model and isinstance(new_model, str) and len(new_model.split('/')) <= 2 and len(new_model) > 2):
            console.print(f"[red]Invalid model name format: {new_model}[/red]")
            return True

        # Test the model with a very short, non-streaming call (optional, can be slow)
        # try:
        # litellm.completion(model=new_model, messages=[{"role":"user", "content":"test"}], max_tokens=5, timeout=10)
        current_llm_model = new_model
        config["default_model"] = new_model # Update general default
        # Update current profile's model too
        profile_name = config.get("current_profile", "default")
        if profile_name in config["profiles"]:
            config["profiles"][profile_name]["model"] = new_model
        else: # Should not happen if config is managed well
            config["profiles"][profile_name] = DEFAULT_CONFIG["profiles"]["default"].copy()
            config["profiles"][profile_name]["model"] = new_model

        save_config(config)
        console.print(f"[green]Switched to model: [cyan]{current_llm_model}[/cyan][/green]")
        # Update system prompt in history if it exists
        for msg in conversation_history:
            if msg["role"] == "system" and not msg.get("type"): # Main system prompt
                msg["content"] = get_system_prompt()
                break
        return True

    elif command == "/save_session":
        if not args:
            console.print("[red]Usage: /save_session <session_name>[/red]")
            return True
        session_name = args[0]
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        session_file = SESSION_DIR / f"{session_name}.json"
        try:
            with open(session_file, "w") as f:
                # Store relevant parts: history, current model, workspace root
                session_data = {
                    "conversation_history": conversation_history,
                    "current_llm_model": current_llm_model,
                    "current_workspace_root": str(current_workspace_root) if current_workspace_root else None,
                    "version": "2.0" # For future compatibility
                }
                json.dump(session_data, f, indent=4)
            console.print(f"[green]Session saved as '[cyan]{session_name}[/cyan]' to {session_file}[/green]")
        except Exception as e:
            console.print(f"[red]Error saving session: {e}[/red]")
        return True

    elif command == "/load_session":
        if not args:
            console.print("[red]Usage: /load_session <session_name>[/red]")
            # List available sessions
            if SESSION_DIR.exists():
                sessions = [f.stem for f in SESSION_DIR.glob("*.json")]
                if sessions:
                    console.print("Available sessions: " + ", ".join(f"[cyan]{s}[/cyan]" for s in sessions))
                else:
                    console.print("No saved sessions found.")
            return True
        session_name = args[0]
        session_file = SESSION_DIR / f"{session_name}.json"
        if session_file.exists():
            try:
                with open(session_file, "r") as f:
                    session_data = json.load(f)
                conversation_history = session_data.get("conversation_history", [])
                current_llm_model = session_data.get("current_llm_model", config.get("default_model"))
                ws_root_str = session_data.get("current_workspace_root")
                if ws_root_str:
                    current_workspace_root = Path(ws_root_str)
                else:
                    current_workspace_root = None

                # Ensure system prompt is up-to-date after loading
                found_system_prompt = False
                for msg in conversation_history:
                    if msg["role"] == "system" and not msg.get("type"): # Main system prompt
                        msg["content"] = get_system_prompt()
                        found_system_prompt = True
                        break
                if not found_system_prompt and conversation_history: # Add if missing (e.g. old session format)
                    conversation_history.insert(0, {"role": "system", "content": get_system_prompt()})
                elif not conversation_history: # Empty history, add system prompt
                     conversation_history.append({"role": "system", "content": get_system_prompt()})


                console.print(f"[green]Session '[cyan]{session_name}[/cyan]' loaded.[/green]")
                console.print(f"Model: [cyan]{current_llm_model}[/cyan], Workspace: [cyan]{current_workspace_root or 'Not set'}[/cyan]")
            except Exception as e:
                console.print(f"[red]Error loading session: {e}[/red]")
        else:
            console.print(f"[red]Session file not found: {session_file}[/red]")
        return True

    elif command == "/list_context":
        file_context_messages = [msg for msg in conversation_history if msg.get("type") == "file_context"]
        if not file_context_messages:
            console.print("[dim]No files are currently in the conversation context.[/dim]")
            return True

        table = Table(title="Files in Context", show_lines=True, border_style="blue")
        table.add_column("#", style="dim")
        table.add_column("File Path", style="cyan")
        table.add_column("Content Preview (lines)", style="green")

        for i, msg in enumerate(file_context_messages):
            path = msg.get("path", "N/A")
            content_preview = "\n".join(msg.get("content", "").splitlines()[:5]) # First 5 lines
            if len(msg.get("content", "").splitlines()) > 5:
                content_preview += "\n[dim]... (more content)[/dim]"
            table.add_row(str(i+1), path, content_preview)
        console.print(table)
        return True

    elif command == "/remove_context":
        if not args:
            console.print("[red]Usage: /remove_context <file_path_or_index_from_/list_context>[/red]")
            return True

        target_to_remove = " ".join(args) # Handle paths with spaces
        file_context_messages = [msg for msg in conversation_history if msg.get("type") == "file_context"]

        removed = False
        try:
            # Try as index first
            idx_to_remove = int(target_to_remove) -1
            if 0 <= idx_to_remove < len(file_context_messages):
                msg_to_remove = file_context_messages[idx_to_remove]
                conversation_history.remove(msg_to_remove)
                console.print(f"[green]Removed '[cyan]{msg_to_remove.get('path', 'Unknown file')}[/cyan]' from context.[/green]")
                removed = True
            else:
                console.print(f"[red]Invalid index: {target_to_remove}[/red]")
        except ValueError:
            # Try as path
            normalized_target_path = normalize_path_str(target_to_remove)
            original_len = len(conversation_history)
            conversation_history[:] = [
                msg for msg in conversation_history
                if not (msg.get("type") == "file_context" and msg.get("path") == normalized_target_path)
            ]
            if len(conversation_history) < original_len:
                console.print(f"[green]Removed '[cyan]{normalized_target_path}[/cyan]' from context.[/green]")
                removed = True

        if not removed and not target_to_remove.isdigit(): # Avoid double error if it was a failed index
            console.print(f"[red]File path '[cyan]{target_to_remove}[/cyan]' not found in context.[/red]")
        return True

    elif command == "/clear_context":
        original_len = len(conversation_history)
        # Keep only the system prompt
        conversation_history[:] = [msg for msg in conversation_history if msg["role"] == "system" and not msg.get("type")]
        if not conversation_history: # Should not happen if initialized correctly
            conversation_history.append({"role": "system", "content": get_system_prompt()})

        if len(conversation_history) < original_len:
             console.print("[green]All file contexts and chat history (except system prompt) cleared.[/green]")
        else:
            console.print("[dim]Context was already minimal or empty.[/dim]")
        return True

    elif command == "/config":
        console.print(Panel(json.dumps(config, indent=2), title="Current Configuration", border_style="magenta"))
        console.print(f"Config file location: [dim]{CONFIG_FILE}[/dim]")
        return True

    elif command == "/set_workspace":
        if not args:
            new_ws_root_str = Prompt.ask("Enter new workspace root path (leave empty to unset)", default=str(current_workspace_root) if current_workspace_root else "")
        else:
            new_ws_root_str = " ".join(args)

        if not new_ws_root_str:
            current_workspace_root = None
            console.print("[blue]Workspace root unset.[/blue]")
        else:
            prospective_root = Path(new_ws_root_str).expanduser().resolve()
            if prospective_root.is_dir():
                current_workspace_root = prospective_root
                console.print(f"[green]Workspace root set to: [cyan]{current_workspace_root}[/cyan][/green]")
            else:
                console.print(f"[red]Error: '{prospective_root}' is not a valid directory.[/red]")
                return True # Handled

        # Update config
        profile_name = config.get("current_profile", "default")
        if profile_name in config["profiles"]:
            config["profiles"][profile_name]["workspace_root"] = str(current_workspace_root) if current_workspace_root else None
        save_config(config)
        # Update system prompt
        for msg in conversation_history:
            if msg["role"] == "system" and not msg.get("type"):
                msg["content"] = get_system_prompt()
                break
        return True

    elif command == "/load_profile":
        if not args:
            console.print("[red]Usage: /load_profile <profile_name>[/red]")
            console.print("Available profiles: " + ", ".join(f"[cyan]{p}[/cyan]" for p in config.get("profiles", {}).keys()))
            return True
        profile_name_to_load = args[0]
        if profile_name_to_load in config.get("profiles", {}):
            config["current_profile"] = profile_name_to_load
            save_config(config) # Save change to current_profile
            # Reload config to apply the new profile settings (model, workspace, auto-add)
            # This is a bit heavy but ensures all profile aspects are applied.
            # Clear current history before loading profile settings like auto-add paths.
            conversation_history.clear()
            conversation_history.append({"role": "system", "content": get_system_prompt()}) # Add fresh system prompt

            # load_config() will re-read from file and apply the new current_profile
            # It also handles auto-adding paths.
            load_config() # This will update global current_llm_model, current_workspace_root, and add files.

            console.print(f"[green]Profile '[cyan]{profile_name_to_load}[/cyan]' loaded.[/green]")
            console.print(f"Model: [cyan]{current_llm_model}[/cyan], Workspace: [cyan]{current_workspace_root or 'Not set'}[/cyan]")
        else:
            console.print(f"[red]Profile '[cyan]{profile_name_to_load}[/cyan]' not found.[/red]")
        return True

    elif command == "/save_profile":
        if not args:
            profile_to_save_name = Prompt.ask("Enter name for new or existing profile to save current settings to", default=config.get("current_profile", "default"))
        else:
            profile_to_save_name = args[0]

        if not profile_to_save_name.isalnum() or not profile_to_save_name: # Basic validation
            console.print("[red]Invalid profile name. Use alphanumeric characters.[/red]")
            return True

        current_settings = {
            "model": current_llm_model,
            "workspace_root": str(current_workspace_root) if current_workspace_root else None,
            # For auto_add_paths, we could ask the user or try to infer from current context
            "auto_add_paths": config["profiles"].get(profile_to_save_name, {}).get("auto_add_paths", []), # Keep existing or prompt
            "custom_ai_ignore": config["profiles"].get(profile_to_save_name, {}).get("custom_ai_ignore", None) # Keep existing
        }
        # Prompt for auto_add_paths and custom_ai_ignore if desired
        if Confirm.ask(f"Update auto-added paths for profile '{profile_to_save_name}'?"):
            paths_str = Prompt.ask("Enter comma-separated paths to auto-add (leave empty for none)")
            current_settings["auto_add_paths"] = [p.strip() for p in paths_str.split(',') if p.strip()]

        if Confirm.ask(f"Update custom .ai_ignore file path for profile '{profile_to_save_name}'?"):
             ignore_path_str = Prompt.ask("Enter path to custom .ai_ignore file (leave empty for none/default)")
             current_settings["custom_ai_ignore"] = ignore_path_str if ignore_path_str else None


        config["profiles"][profile_to_save_name] = current_settings
        config["current_profile"] = profile_to_save_name # Switch to it if newly saved
        save_config(config)
        console.print(f"[green]Settings saved to profile '[cyan]{profile_to_save_name}[/cyan]'.[/green]")
        return True

    elif command == "/help":
        print_help()
        return True

    return False # Not a known slash command

def remove_file_from_context(normalized_file_path: str, quiet: bool = False):
    """Removes a specific file's content from conversation history."""
    global conversation_history
    initial_len = len(conversation_history)
    # Remove based on the 'path' stored in the message
    conversation_history[:] = [
        msg for msg in conversation_history
        if not (msg.get("type") == "file_context" and msg.get("path") == normalized_file_path)
    ]
    if not quiet and len(conversation_history) < initial_len:
        console.print(f"[dim]Updated context: Removed old version of '{normalized_file_path}'.[/dim]")


def print_help():
    help_text = f"""
[bold bright_blue]AI Code Assistant Commands:[/bold bright_blue]

[bold cyan]File Context Management:[/bold cyan]
  /add <path>             Add a file or directory to the conversation context.
                          Uses patterns from `.ai_ignore` in CWD or profile.
  /list_context           Show files currently in context.
  /remove_context <path_or_index>
                          Remove a file from context by its path or index from /list_context.
  /clear_context          Clear all files and chat history (keeps system prompt).

[bold cyan]LLM & Session Control:[/bold cyan]
  /setmodel <model_name>  Switch to a different LLM (e.g., gpt-4, claude-2).
                          LiteLLM API keys must be set as environment variables.
  /save_session <name>    Save current chat history and settings.
  /load_session <name>    Load a previously saved session.

[bold cyan]Workspace & Profiles:[/bold cyan]
  /set_workspace <path>   Set the project's root directory (for relative paths).
                          Leave path empty to unset.
  /load_profile <name>    Load a saved project profile (model, workspace, etc.).
  /save_profile [name]    Save current settings as a new profile or update existing.

[bold cyan]Utility:[/bold cyan]
  /config                 Display current application configuration.
  /help                   Show this help message.
  exit, quit              Exit the application.

[bold bright_blue]Configuration File:[/bold bright_blue] [dim]{CONFIG_FILE}[/dim]
[bold bright_blue]Session Files:[/bold bright_blue] [dim]{SESSION_DIR}[/dim]
[bold bright_blue]Default Ignore File Example:[/bold bright_blue] [dim]{AI_IGNORE_EXAMPLE_FILE}[/dim]
 (or create `.ai_ignore` in your current working directory)
    """
    console.print(Panel(Markdown(help_text), title="Help", border_style="blue", expand=False))


# --------------------------------------------------------------------------------
# 9. Main Interactive Loop
# --------------------------------------------------------------------------------
def main():
    global conversation_history, config # Ensure global config is accessible

    # Ensure config is loaded and applied (redundant if load_config() is called at module level, but safe)
    config = load_config()

    # Initialize conversation history with the system prompt
    if not conversation_history or not any(msg["role"] == "system" and not msg.get("type") for msg in conversation_history):
        conversation_history.insert(0, {"role": "system", "content": get_system_prompt()})

    # Welcome panel
    welcome_text = f"""[bold bright_blue]🐋 AI Code Assistant v2.0[/bold bright_blue]
[dim][blue]Powered by LiteLLM ([underline][link=https://litellm.ai/]https://litellm.ai/[/link][/underline])[/blue][/dim]
Current Model: [bright_cyan]{current_llm_model}[/bright_cyan]
Workspace: [bright_cyan]{current_workspace_root or 'Not set'}[/bright_cyan]
Type [bold cyan]/help[/bold cyan] for commands."""

    console.print(Panel.fit(
        welcome_text,
        border_style="bright_blue",
        padding=(1, 2),
        title="[bold bright_cyan]🤖 AI Code Assistant[/bold bright_cyan]",
        title_align="center"
    ))
    console.print()

    while True:
        try:
            user_input_raw = prompt_session.prompt("🔵 You> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[bold yellow]👋 Exiting gracefully...[/bold yellow]")
            break

        if not user_input_raw:
            continue

        if user_input_raw.lower() in ["exit", "quit"]:
            console.print("[bold bright_blue]👋 Goodbye! Happy coding![/bold bright_blue]")
            break

        if user_input_raw.startswith("/"):
            if try_handle_slash_command(user_input_raw):
                continue
            else: # Unknown slash command
                console.print(f"[red]Unknown command: {user_input_raw.split()[0]}. Type /help for available commands.[/red]")
                continue

        # Process as a message to the LLM
        process_user_message(user_input_raw)

    console.print("[bold blue]✨ Session finished. Thank you for using AI Code Assistant![/bold blue]")

if __name__ == "__main__":
    load_dotenv() # Load .env file for API keys if present (LiteLLM will pick them up)
    main()
