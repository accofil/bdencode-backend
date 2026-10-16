#!/bin/sh
# Start bdencode-worker.service when it is enabled but stopped.
#
# The worker's ExecCondition (the recovery check) can fail while the disk is
# full; systemd then marks the unit skipped, not failed, and never tries again.
# This runs every two minutes from bdencode-worker-ensure.timer.  It acts only
# on a unit that is plainly "inactive" or "failed": never while systemd is
# stopping or starting it, and never while an update, an installer transaction
# or a recovery owns the services (3.8.2 broke an update by queueing a start
# while the installer was restarting the worker).
#
# A deliberate stop for maintenance is kept with
#   systemctl disable --now bdencode-worker
set -u

unit=bdencode-worker.service
state_dir=${BDENCODE_STATE_DIR:-/var/lib/bdencode}

systemctl is-enabled --quiet "$unit" || exit 0

state=$(systemctl show -p ActiveState --value "$unit" 2>/dev/null)
case "$state" in
    inactive|failed) ;;
    *) exit 0 ;;
esac

for marker in \
    install-transactions/active \
    install-transactions/services-pending \
    update-runtime/active.json \
    apt-transactions/active; do
    [ -e "$state_dir/$marker" ] && exit 0
done

case "$(systemctl show -p ActiveState --value bdencode-update.service 2>/dev/null)" in
    inactive|failed|"") ;;
    *) exit 0 ;;
esac

systemctl reset-failed "$unit" || true
exec systemctl start --no-block "$unit"
