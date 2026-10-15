#!/bin/bash
# Stage 2: paginate TWAP slice fills (userFillsByTime omits them), then run the generic analyzer.
cd "$(dirname "$0")"
PY=/Users/jim/projects/vault/.venv/bin/python
N=${N:-3}
: > logs/_stage2.log
i=0
while read -r a; do
  [ -z "$a" ] && continue
  ( $PY scripts/fetch_twap.py "$a" > "logs/twap_${a:0:10}.log" 2>&1 \
    && $PY scripts/analyze.py "${a:0:10}" > "data/${a:0:10}/analysis.txt" 2>&1 \
    && echo "ok ${a:0:10} $(grep -c '' data/${a:0:10}/analysis.txt) lines" >> logs/_stage2.log \
    || echo "FAIL ${a:0:10}" >> logs/_stage2.log ) &
  i=$((i+1))
  if [ $((i % N)) -eq 0 ]; then wait; fi
done < addrs.txt
wait
echo "ALL STAGE2 DONE" >> logs/_stage2.log
