#!/bin/bash
cd "$(dirname "$0")"
PY=/Users/jim/projects/vault/.venv/bin/python
: > logs/_stage3.log
i=0
while read -r a; do
  [ -z "$a" ] && continue
  s="${a:0:10}"
  ( if $PY scripts/analyze.py "$s" > "data/$s/analysis.txt.new" 2>&1; then
      mv "data/$s/analysis.txt.new" "data/$s/analysis.txt"; echo "ok $s" >> logs/_stage3.log
    else
      echo "FAIL $s" >> logs/_stage3.log
    fi ) &
  i=$((i+1)); [ $((i % 3)) -eq 0 ] && wait
done < addrs.txt
wait
echo "STAGE3 DONE" >> logs/_stage3.log
