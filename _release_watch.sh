#!/bin/bash
# v0.9.7 发布守护: 轮询 GitHub 连通性, 通则 push + release, 全程日志
cd /d/TEMP/PolyXRD || exit 1
LOG=_release_watch.log
: > "$LOG"
echo "[watch] start $(date +%T)" >> "$LOG"

probe() {
  curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 https://github.com 2>/dev/null
}

PUSH_MAIN=0
PUSH_TAG=0
RELEASE=0

for i in $(seq 1 60); do
  code=$(probe)
  echo "[try $i] probe=$code $(date +%T)" >> "$LOG"
  if [ "$code" != "200" ]; then
    sleep 30
    continue
  fi
  if [ "$PUSH_MAIN" = "0" ]; then
    if timeout 300 git push origin main >> "$LOG" 2>&1; then
      PUSH_MAIN=1; echo "[ok] push main $(date +%T)" >> "$LOG"
    else
      echo "[retry] push main failed" >> "$LOG"; sleep 15; continue
    fi
  fi
  if [ "$PUSH_TAG" = "0" ]; then
    if timeout 120 git push origin v0.9.7 >> "$LOG" 2>&1; then
      PUSH_TAG=1; echo "[ok] push tag $(date +%T)" >> "$LOG"
    else
      echo "[retry] push tag failed" >> "$LOG"; sleep 15; continue
    fi
  fi
  if [ "$RELEASE" = "0" ]; then
    echo "[run] release script $(date +%T)" >> "$LOG"
    if timeout 1800 pwsh -NoProfile -File scripts/create_github_release_v0.9.7.ps1 >> "$LOG" 2>&1; then
      RELEASE=1; echo "[done] RELEASE COMPLETE $(date +%T)" >> "$LOG"
      break
    else
      echo "[retry] release script failed (可重跑, 幂等)" >> "$LOG"; sleep 15; continue
    fi
  fi
  sleep 5
done

if [ "$RELEASE" = "1" ]; then
  echo "RESULT=SUCCESS" >> "$LOG"
else
  echo "RESULT=INCOMPLETE (main=$PUSH_MAIN tag=$PUSH_TAG release=$RELEASE)" >> "$LOG"
fi
