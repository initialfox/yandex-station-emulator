#!/bin/sh
# Keep the legacy firmware adbd alive even after a nonzero exit or signal.
# Deliberately no `set -e`: a failed child must not terminate its supervisor.
set -u
root=${MINI2_ADB_ROOT:-/mini2}
chroot_cmd=${MINI2_ADB_CHROOT:-chroot}
delay=${MINI2_ADB_RETRY_SECONDS:-2}
log="$root/tmp/adbd.log"
while :; do
    # Some builds daemonize; never launch duplicates while one is alive.
    if pidof adbd >/dev/null 2>&1; then
        sleep "$delay"
        continue
    fi
    if [ -f "$log" ] && [ "$(wc -c < "$log")" -gt 65536 ]; then
        mv -f "$log" "$log.previous"
    fi
    printf '%s starting adbd\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >>"$log"
    "$chroot_cmd" "$root" /usr/bin/adbd >>"$log" 2>&1
    status=$?
    printf '%s adbd exited rc=%s; retry in %ss\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$status" "$delay" >>"$log"
    sleep "$delay"
done
