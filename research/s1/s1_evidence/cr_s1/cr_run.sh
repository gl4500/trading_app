#!/bin/sh
# S1 Task 9 round 2: execute every shard session under WORK (arg 1) with at most 4 concurrent cosmic-ray processes
# (controller cap: the live app runs on this machine). Longest shards first.
W="$1"
CR=/c/Users/gl450/.coordination/trading_app/testenv/Scripts/cosmic-ray.exe
for s in s1_run_s0 s1_run_s1 s1_run_s2 s1_run_s3 s1_run_s4 s1_run_s5 s1_checkpoint_s0 s1_checkpoint_s1 s1_seal_s0 \
         s1_books_s0; do echo "$s"; done | xargs -P 4 -I{} sh -c \
  "cd '$W/{}' && date -u +%FT%TZ > started.txt && '$CR' exec cr.toml cr.sqlite > cr_exec.log 2>&1; echo rc=\$? > done.txt; date -u +%FT%TZ >> done.txt; echo {} done"
