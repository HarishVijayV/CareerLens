# Airflow, plus the two things the stock image cannot do.
#
# The DAG shells out to the pipeline's own scripts, so whatever those need must exist HERE
# too — Airflow being installed is not the same as the work being runnable. On the stock
# image the DAG parsed cleanly and then failed at step 3 with "java: Permission denied",
# which is the confusing kind of failure: the orchestrator is fine, the thing it
# orchestrates is not.
#
# Two additions:
#   * a JRE — PySpark is a thin Python wrapper around a Scala engine that runs on the JVM,
#     so no Java means no Spark, regardless of the Python packages being present
#   * the pipeline's Python requirements, so `python spark_jobs/etl_clean_jobs.py` resolves
#     its imports
FROM apache/airflow:2.9.3-python3.11

USER root

# default-jre-headless, not default-jre: the full package pulls in X11 libraries for a
# container that will never draw anything.
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Spark finds the JVM through JAVA_HOME. Resolved from the java binary rather than
# hardcoded, because the path differs by architecture (x86 vs the ARM you get on Oracle
# Cloud or an M-series Mac) and a hardcoded path breaks silently on the other one.
RUN JAVA_BIN=$(readlink -f "$(which java)") \
    && echo "JAVA_HOME=$(dirname "$(dirname "$JAVA_BIN")")" >> /etc/environment
ENV JAVA_HOME=/usr/lib/jvm/default-java

# Back to the airflow user before installing Python packages. Installing them as root puts
# them somewhere the airflow user cannot import from, and the image builds perfectly while
# every DAG run fails on ImportError.
USER airflow

# Install against Airflow's OWN constraints file, and this is not optional.
#
# Installing pipeline/requirements.txt directly upgraded SQLAlchemy to 2.x, which Airflow
# 2.9 does not support. The image built successfully and then every container crashed on
# startup with "Type annotation for TaskInstance.dag_model can't be correctly interpreted"
# — an error deep in Airflow's own models that says nothing about the actual cause, which
# was a dependency this Dockerfile silently replaced.
#
# The constraints file pins every package Airflow was tested against, so pip resolves our
# additions AROUND them instead of over them. Publishing one is how Airflow expects images
# to be extended; ignoring it is the single most common way to break an Airflow image.
ARG AIRFLOW_VERSION=2.9.3
ARG PYTHON_VERSION=3.11
ARG CONSTRAINTS="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

# Only what the DAG's scripts actually import, not the pipeline's whole requirements file.
# dbt and its adapters are deliberately absent: they drag in their own pinned SQLAlchemy
# and jinja2, and the dbt steps run through the `dbt` CLI rather than being imported.
RUN pip install --no-cache-dir --constraint "${CONSTRAINTS}" \
        "pyspark==3.5.1" \
        "pandas" \
        "pyarrow" \
        "httpx" \
        "psycopg[binary]" \
        "kafka-python" \
        "faker"

# dbt in its OWN virtualenv, called by absolute path.
#
# dbt pins jinja2 and SQLAlchemy versions that conflict with Airflow's, so installing it
# alongside breaks one or the other — that is what the constraints file above is protecting
# against, and dbt cannot be made to fit inside those constraints.
#
# A separate venv sidesteps the argument entirely: two Pythons, two dependency trees, no
# negotiation. The DAG invokes /opt/dbt-venv/bin/dbt rather than `dbt`, so it cannot
# accidentally pick up a different one from PATH.
#
# This is the standard way to run dbt under Airflow without the two fighting.
#
# Under $HOME rather than /opt: the airflow user cannot write to /opt, so creating it there
# failed with "Permission denied: '/opt/dbt-venv'". Switching to root to create it would
# work and then leave a venv the airflow user cannot install into later — putting it
# somewhere the running user already owns avoids the whole question.
RUN python -m venv /home/airflow/dbt-venv \
    && /home/airflow/dbt-venv/bin/pip install --no-cache-dir \
        "dbt-core==1.8.7" "dbt-postgres==1.8.2"
