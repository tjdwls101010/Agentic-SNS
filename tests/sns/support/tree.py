"""The skill's tree as git sees it, for the structure tests: what a sandbox or a shell leaves behind (an empty
`.claude/.cc-writes` directory, `__pycache__`, `.DS_Store`) is not part of it."""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def children(root):
    """{name: is_dir} of what sits directly in `root`: tracked files and untracked ones git does not ignore. Empty
    directories and ignored files are not listed."""
    root = Path(root).resolve()
    listed = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', str(root)],
                            cwd=REPO, capture_output=True, text=True, check=True).stdout.split('\0')
    found = {}
    for line in filter(None, listed):
        parts = (REPO / line).relative_to(root).parts
        found[parts[0]] = found.get(parts[0], False) or len(parts) > 1
    return found


def folders(root):
    return {name for name, is_dir in children(root).items() if is_dir}
