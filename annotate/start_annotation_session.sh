#!/bin/bash
# Start local annotation session (local dev only — team annotation is at https://dev.qongsystems.com/ls/)
# Usage: ./annotate/start_annotation_session.sh
#   Starts label-studio + web locally for offline annotation work.

set -e
cd "$(dirname "$0")/.."

echo "Starting annotation session (local)..."

# Prevent Mac sleep
caffeinate -i &
CAFFEINATE_PID=$!
echo "Sleep prevention active (PID $CAFFEINATE_PID)"

# Ensure services are running
echo "Starting Docker services (web, label-studio, nginx)..."
WEBAPP_BASE_URL=http://localhost:8000 docker compose up -d web label-studio nginx
sleep 5

echo ""
echo "Services ready:"
echo "  Webapp:       http://localhost:8000"
echo "  Label Studio: http://localhost:8080  or  http://localhost:9000/ls/"
echo ""
echo "Login: tnb@qongsystems.com / <password>"
echo ""
echo "NOTE: For team annotation use https://dev.qongsystems.com/ls/ (GCP, always on)"
echo "--------------------------------------------"
echo "Press Ctrl+C to stop the session"
echo ""

trap "kill $CAFFEINATE_PID 2>/dev/null; echo 'Session ended.'" EXIT

# Keep script alive
wait $CAFFEINATE_PID
