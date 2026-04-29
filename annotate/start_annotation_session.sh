#!/bin/bash
# Start annotation session: webapp + Label Studio via single ngrok tunnel on port 9000
# Usage: ./annotate/start_annotation_session.sh

set -e
cd "$(dirname "$0")/.."

echo "Starting annotation session..."

# Prevent Mac sleep
caffeinate -i &
CAFFEINATE_PID=$!
echo "Sleep prevention active (PID $CAFFEINATE_PID)"

# Ensure webapp, label-studio, and nginx are running
echo "Starting services (web, label-studio, nginx)..."
docker compose up -d web label-studio nginx
sleep 5

echo ""
echo "Services ready:"
echo "  Webapp:       http://localhost:8000"
echo "  Label Studio: http://localhost:8080"
echo "  Combined:     http://localhost:9000       (/ = webapp, /ls/ = Label Studio)"
echo ""
echo "Starting ngrok tunnel on port 9000..."
echo "Share the ngrok URL with your team:"
echo "  <ngrok-url>/       → webapp"
echo "  <ngrok-url>/ls/    → Label Studio"
echo "Login: tnb@qongsystems.com / Qong@2024"
echo "--------------------------------------------"
echo "Press Ctrl+C to stop the session"
echo ""

trap "kill $CAFFEINATE_PID 2>/dev/null; echo 'Session ended.'" EXIT

ngrok http 9000
