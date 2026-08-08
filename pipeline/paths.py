"""
Windows MAX_PATH workaround.

Windows caps normal paths at 260 characters. This project lives in a deep folder, and
Spark writes files with long generated names like
`part-00000-99a690f4-08c0-4fbb-9d3d-a64a89b93ac7-c000.snappy.parquet`, so absolute paths
here land around 280 characters.

The confusing part: Spark WRITES those files fine (the JVM uses long-path-aware APIs),
and `Path.glob()` FINDS them fine, but `open()` then fails with FileNotFoundError on a
file you can see with your own eyes. Prefixing an absolute path with `\\?\` tells Windows
to skip MAX_PATH parsing and use the extended-length API instead.

Permanent alternatives, if you'd rather not carry this helper:
  * Enable long paths system-wide (admin PowerShell):
      New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
        -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
  * Or move the project somewhere shallow, e.g. C:\dev\careerlens.
"""
import os
from pathlib import Path


def long_path(path: str | Path) -> str:
    """Return a string path safe to hand to open() even past MAX_PATH on Windows."""
    resolved = Path(path).resolve()
    if os.name != "nt":
        return str(resolved)

    text = str(resolved)
    if text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):  # UNC network share, e.g. \\server\share\...
        return "\\\\?\\UNC\\" + text.lstrip("\\")
    return "\\\\?\\" + text
