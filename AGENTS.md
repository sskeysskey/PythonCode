# Codebase Guide for Autonomous Agents

This file documents the build system, code style, and conventions for the `python_code` repository.

## 1. Project Overview

- **Type**: Collection of personal automation scripts (Python, AppleScript, Shell, JS).
- **Purpose**: News scraping, clipboard manipulation, text processing, and system automation.
- **Platform**: **macOS** primary (AppleScript usage, file paths).
- **Structure**:
    - Root: Main utility scripts.
    - `Selenium_News/`: Web scraping scripts (Selenium).
    - `Modules/`: Shared utility modules.
    - `Resource/`: Data/config files.

## 2. Environment & Commands

### Build & Run
There is no formal build system. Scripts are executed directly.

- **Run Script**:
  ```bash
  python3 <script_path>
  # Example: python3 Doubao_News.py
  ```

- **Dependencies**:
  - No `requirements.txt` or `poetry.lock` detected at root.
  - Common libs: `selenium`, `pyperclip`, `transformers`, `torch`.
  - Install missing packages via `pip install <package>`.

### Testing
There is **NO** formal test suite (pytest/unittest).

- **How to Test**:
  1. **Run the script directly**: Most scripts have `if __name__ == "__main__":` blocks.
  2. **Use `test.py`**: A scratchpad for testing snippets.
  3. **Verification**: Check output files (TXT/HTML) in `News/` or `Website/news/` directories.

- **Linting**:
  - No automatic linter configured.
  - **Rule**: Follow PEP 8 best practices generally, but respect existing file consistency.

## 3. Code Style & Conventions

### Formatting
- **Indentation**: **4 spaces**.
- **Line Length**: Soft limit 100-120 chars (readability).
- **Encoding**: **CRITICAL**. Use `utf-8-sig` for file I/O to ensure compatibility (especially for CSV/TXT files used on Windows or by Excel).
  ```python
  with open(file_path, 'r', encoding='utf-8-sig') as f:
      ...
  ```

### Naming Conventions
- **Files**: Mixed conventions.
    - Root scripts: `Camel_Snake_Case.py` (e.g., `Doubao_News.py`, `Article_Copier.py`).
    - Submodules: `snake_case.py` (e.g., `selenium_wsj_cn.py`).
    - **Rule**: When creating new files, match the convention of the directory.
- **Functions/Variables**: `snake_case` (e.g., `check_english_ratio`, `get_clipboard_content`).
- **Classes**: `PascalCase`.
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `TXT_DIRECTORY`, `USER_HOME`).

### Type Hints
- **Encouraged**: Use Python type hints for new code.
  ```python
  def process_text(content: str, ratio: float = 0.5) -> bool:
  ```

### Comments & Documentation
- **Language**: **Bilingual** (English & Simplified Chinese).
- **Docstrings**: Required for complex functions.
- **Logs/Print**: Chinese output is common for user-facing status.

### Error Handling
- Use `try...except` for file I/O and network requests.
- Fail gracefully with a printed message rather than crashing, if possible.
- **Cleanup**: Ensure temporary files (in `/tmp` or `tempfile`) are removed in `finally` blocks or at end of script.

## 4. Critical Constraints & Patterns

### File Paths
- **Absolute Paths**: Use `os.path.join` with `os.path.expanduser("~")`.
- **Avoid Hardcoding**: Do not hardcode `/Users/yanzhang` unless necessary. Use `~` or dynamic detection.
  ```python
  USER_HOME = os.path.expanduser("~")
  BASE_DIR = os.path.join(USER_HOME, "Coding", "News")
  ```

### Clipboard & System Interactions
- Uses `pyperclip` for clipboard.
- Uses `subprocess` for calling macOS specific commands (e.g., `osascript`).

### Data Directory Structure
- Scripts often read/write to:
  - `~/Coding/News`
  - `~/Coding/Website/news`
  - `~/Downloads`

## 5. Agent Instructions

When working on this codebase:
1. **Check existing patterns**: Read 1-2 related files before writing.
2. **Preserve encodings**: Always check if `utf-8-sig` is needed.
3. **No over-engineering**: Do not introduce complex build tools or strict linters unless asked. Keep it simple and script-based.
4. **Manual Verification**: Since there are no tests, verifying your code means running it and checking the side effects (files created, clipboard changed).
