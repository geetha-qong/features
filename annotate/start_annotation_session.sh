#!/bin/bash
# Start annotation session: webapp + Label Studio via single ngrok tunnel on port 9000
# Usage: ./annotate/start_annotation_session.sh [ngrok-url]
#   If ngrok-url is provided, WEBAPP_BASE_URL is set so LS tile images load via that URL.
#   Otherwise tiles load via internal Docker URL (local-only access).

set -e
cd "$(dirname "$0")/.."

echo "Starting annotation session..."

# Prevent Mac sleep
caffeinate -i &
CAFFEINATE_PID=$!
echo "Sleep prevention active (PID $CAFFEINATE_PID)"

# Ensure services are running
echo "Starting Docker services (web, label-studio, nginx)..."
docker compose up -d web label-studio nginx
sleep 5

echo ""
echo "Services ready:"
echo "  Webapp (direct):       http://localhost:8000"
echo "  Label Studio (direct): http://localhost:8080  or  http://localhost:9001"
echo "  Combined (ngrok):      http://localhost:9000  (/ = webapp, /ls/ = Label Studio)"
echo ""
echo "Starting ngrok tunnel on port 9000..."
echo "Once ngrok shows the URL, restart the web container with WEBAPP_BASE_URL set:"
echo "  WEBAPP_BASE_URL=<ngrok-url> docker compose up -d web"
echo ""
echo "Team access:"
echo "  <ngrok-url>/          → Upload P&IDs, view jobs"
echo "  <ngrok-url>/ls/       → Annotate tiles in Label Studio"
echo "Login: tnb@qongsystems.com / Qong@2024"
echo "--------------------------------------------"
echo "Press Ctrl+C to stop the session"
echo ""

trap "kill $CAFFEINATE_PID 2>/dev/null; echo 'Session ended.'" EXIT

ngrok http 9000
