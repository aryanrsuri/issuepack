#!/usr/bin/env python3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

issues = Path.cwd() / ".issues"
issues.mkdir(exist_ok=True)
ids = [
    int(p.stem.rsplit("#", 1)[-1])
    for p in issues.glob("*.txt")
    if p.stem.rsplit("#", 1)[-1].isdigit()
]
id = max(ids, default=0) + 1
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
issue = issues / f"{timestamp}#{id}.txt"
# issue.touch(exist_ok=False)
issue.write_text(f"I={id}\nD={timestamp}\nS=NOT_DONE\nT=\n", encoding="utf-8")
print(issue)
