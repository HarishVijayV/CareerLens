"""
Shared Spark setup. Every Spark script imports build_spark() from here so the session is
configured identically everywhere, and so the three environment gotchas below are solved
once instead of in every script.

All three were hit for real while building this on Windows — they're documented in
docs/DATA_ENGINEERING.md's troubleshooting section too:

1. PYSPARK_PYTHON — Spark launches separate Python worker processes. On Windows a bare
   `python` often resolves to the Microsoft Store alias stub rather than the real
   interpreter; the workers then die with "Python was not found" and the job fails with
   a SocketTimeoutException that says nothing about the real cause. Pinning both vars to
   sys.executable makes workers use the exact interpreter that launched the driver.

2. JAVA_HOME — Spark runs on the JVM. If Java isn't on PATH the failure is immediate and
   obvious; auto-detecting a local JDK install keeps setup to one step.

3. HADOOP_HOME / winutils.exe — Spark uses Hadoop's filesystem layer even when reading
   plain local files, and on Windows that layer needs winutils.exe + hadoop.dll present.
   Without it, reads and aggregations work fine but every WRITE fails with
   "HADOOP_HOME and hadoop.home.dir are unset" — a confusing error, since the job looks
   healthy right up until it saves. Not needed on Linux/macOS or in Docker.
"""
import os
import sys
from pathlib import Path

os.environ["PYSPARK_PYTHON"] = sys.executable
os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable


def _autodetect(env_var: str, candidates: list[Path]) -> None:
    """Set env_var to the first candidate path that exists, unless already set."""
    if os.environ.get(env_var):
        return
    for path in candidates:
        if path.exists():
            os.environ[env_var] = str(path)
            return


_home = Path.home()

_autodetect(
    "JAVA_HOME",
    sorted(_home.glob(".jre/jdk-*"), reverse=True)      # installed via `python -m jdk`
    + sorted(_home.glob(".jdk/jdk-*"), reverse=True)
    + sorted(Path("C:/Program Files/Eclipse Adoptium").glob("jdk-*"), reverse=True)
    + sorted(Path("C:/Program Files/Java").glob("jdk*"), reverse=True),
)

_autodetect("HADOOP_HOME", [_home / "hadoop"])

# Spark shells out to $JAVA_HOME/bin/java and $HADOOP_HOME/bin/winutils.exe, so both
# need to be on PATH for the child processes, not just set as variables.
for _var in ("JAVA_HOME", "HADOOP_HOME"):
    _root = os.environ.get(_var)
    if _root:
        os.environ["PATH"] = f"{_root}{os.sep}bin{os.pathsep}" + os.environ["PATH"]

from pyspark.sql import SparkSession  # noqa: E402  (must follow the env setup above)


def build_spark(app_name: str, driver_memory: str = "4g") -> SparkSession:
    return (
        SparkSession.builder.appName(app_name)
        # local[*] uses every core on this machine. Pointing at a real cluster (YARN,
        # EMR, Databricks) is a master-URL change — no other code in these jobs changes.
        .master("local[*]")
        .config("spark.driver.memory", driver_memory)
        # Spark's default of 200 shuffle partitions is huge overkill for laptop-sized
        # data — it creates 200 tiny tasks whose scheduling overhead dwarfs the actual
        # work. Tuning this is one of the most common real-world Spark speedups.
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )
