#!/usr/bin/env python
"""
Classic Hadoop Streaming mapper — reads job postings (one JSON per line) from stdin,
emits one `skill\t1` line per required skill to stdout. Hadoop Streaming lets you write
map/reduce steps in any language that reads stdin/writes stdout; this is the real,
runnable mapper half of the MapReduce job described in docs/DATA_ENGINEERING.md.

Run for real against the Dockerized single-node cluster (bigdata profile):
    hadoop jar $HADOOP_HOME/share/hadoop/tools/lib/hadoop-streaming-*.jar \
        -files mapper.py,reducer.py \
        -mapper mapper.py -reducer reducer.py \
        -input /raw/postings.jsonl -output /curated/skill_counts

Or just pipe it locally to prove the logic without a cluster:
    cat data/raw/postings.jsonl | python mapper.py | sort | python reducer.py
"""
import json
import sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        posting = json.loads(line)
    except json.JSONDecodeError:
        continue

    for skill in posting.get("required_skills", []) or []:
        # tab-separated key/value — the format Hadoop Streaming's shuffle sorts on
        print(f"{skill}\t1")
