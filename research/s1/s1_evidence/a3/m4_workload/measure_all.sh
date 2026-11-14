#!/bin/bash
# H4 row 439: every declared cell, in the pre-bound record's sample counts (low-Q n=5, high-Q n=3).
S=C:/Users/gl450/AppData/Local/Temp/claude/C--Users-gl450/c661c7e7-0401-4122-9c4b-9345620dbebb/scratchpad
PY=C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe
W=C:/Users/gl450/trading_app-s1/research/s1/s1_evidence/a3/m4_workload
S1=C:/Users/gl450/trading_app-s1/research/s1
for wl in lowq highq; do
  n=5; [ $wl = highq ] && n=3
  for cont in idle contended; do
    for cache in warm cold; do
      echo "[$(date -u +%T)] $wl $cont $cache n=$n"
      $PY $W/driver.py measure --pristine $S/m4fx_$wl --runs-dir $W/runs --contention $cont --cache $cache --n $n --scratch $S --s1 $S1 2>&1 | tail -$n
    done
  done
done
echo "[$(date -u +%T)] all cells done"
