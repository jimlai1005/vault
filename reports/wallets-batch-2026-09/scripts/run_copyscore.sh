#!/bin/bash
# T2: run copyscore.py v0.3 for all 22 wallets in addrs.txt, N=2 concurrent, one
# wallet's failure does not stop the others. Progress -> logs/_copyscore.log,
# per-wallet output -> logs/copyscore_<addr10>.log.
cd "$(dirname "$0")/.."
PY=/Users/jim/projects/vault/.venv/bin/python
N=${N:-2}
: > logs/_copyscore.log
i=0
while read -r a; do
  [ -z "$a" ] && continue
  s="${a:0:10}"
  (
    t0=$(date +%s)
    if $PY scripts/copyscore.py "$s" > "logs/copyscore_${s}.log" 2>&1; then
      t1=$(date +%s)
      echo "ok $s $((t1-t0))s" >> logs/_copyscore.log
    else
      t1=$(date +%s)
      echo "FAIL $s $((t1-t0))s -- see logs/copyscore_${s}.log" >> logs/_copyscore.log
    fi
  ) &
  i=$((i+1))
  if [ $((i % N)) -eq 0 ]; then wait; fi
done < addrs.txt
wait
echo "ALL COPYSCORE DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> logs/_copyscore.log
