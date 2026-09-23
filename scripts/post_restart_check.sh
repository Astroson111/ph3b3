#!/usr/bin/env bash
# Post-restart self-knowledge check.
#
# A config change that silently breaks what she believes about herself has no
# symptom until someone asks her what she can do — and gets a polite wrong
# answer. This fails the same day instead.
#
#   scripts/post_restart_check.sh
#
# Exit 0 = her self-knowledge matches the config. 1 = it does not. 2 = could
# not check (service or judge down), which is NOT a pass.
set -u
cd "$(dirname "$0")/.."

for i in $(seq 1 30); do
    if curl -sk -o /dev/null -m 3 "https://127.0.0.1:${PH3B3_PORT:-7331}/ready"; then break; fi
    sleep 2
done

out=$(.venv/bin/python -m pytest tests/test_self_knowledge_smoke.py -q 2>&1)
code=$?
echo "$out" | tail -5

if echo "$out" | grep -q "GRADER UNFIT"; then
    echo "post-restart check: COULD NOT CHECK — the grader could not tell a"
    echo "  deflection from an answer. That is not a pass."
    exit 2
fi
if echo "$out" | grep -qE "no tests ran|[0-9]+ skipped" && [ $code -eq 0 ]; then
    if ! echo "$out" | grep -qE "[0-9]+ passed"; then
        echo "post-restart check: COULD NOT CHECK — service or judge unreachable."
        exit 2
    fi
fi
[ $code -eq 0 ] && echo "post-restart check: her self-knowledge matches the config." \
                || echo "post-restart check: FAILED — she is not answering from her config."
exit $code
