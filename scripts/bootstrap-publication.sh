#!/usr/bin/env bash
# The lock and completion receipt survive a disconnected host-side docker exec.
set -euo pipefail
work="$1"
exec 9>/var/jenkins_home/datenportal-bootstrap.lock
flock -n 9 || exit 75
trap 'status=$?; printf "%s\n" "$status" > "$work/exit-code"; exit "$status"' EXIT
tar -C /var/jenkins_home/gretl-datenportal/topic-repo \
  --exclude=.git --exclude=.gradle --exclude=build --exclude=.DS_Store \
  -cf - . | tar -C "$work" -xf -
cd "$work"
./shared/bin/gradlew-java17.sh --no-daemon \
  -I "$work/shared/gradle/init.gradle" initializePublication \
  -Ps3Publish=true -PgitWriteBack=false -PreloadPortal=false </dev/null
