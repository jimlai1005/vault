#!/bin/bash
# Fetch all wallets, N at a time. Read-only public HL info endpoints.
cd "$(dirname "$0")"
PY=/Users/jim/projects/vault/.venv/bin/python
N=${N:-4}
i=0
while read -r a; do
  [ -z "$a" ] && continue
  ( $PY scripts/fetch_wallet.py "$a" > "logs/fetch_${a:0:10}.log" 2>&1; \
    echo "done $a rc=$?" >> logs/_progress.log ) &
  i=$((i+1))
  if [ $((i % N)) -eq 0 ]; then wait; fi
done < addrs.txt
wait
echo "ALL FETCH DONE" >> logs/_progress.log
