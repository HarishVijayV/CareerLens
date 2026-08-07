#!/usr/bin/env python
"""
Classic Hadoop Streaming reducer — relies on Hadoop's shuffle having SORTED stdin by key
(that's why the local pipe test uses `sort` in between mapper and reducer: it's standing
in for what Hadoop's shuffle phase does automatically on a real cluster). Because the
input is sorted, all counts for the same skill arrive consecutively, so a running total
that resets on key-change is enough — no need to hold every key in memory at once.
"""
import sys

current_skill = None
current_count = 0

for line in sys.stdin:
    skill, count = line.strip().split("\t")
    count = int(count)

    if skill == current_skill:
        current_count += count
    else:
        if current_skill is not None:
            print(f"{current_skill}\t{current_count}")
        current_skill, current_count = skill, count

if current_skill is not None:
    print(f"{current_skill}\t{current_count}")
