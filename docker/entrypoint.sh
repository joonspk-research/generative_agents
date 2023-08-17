#!/bin/bash
set -e

HOST="${DJANGO_HOST:-"0.0.0.0"}"
PORT="${DJANGO_PORT:-"8000"}"

cat > /app/reverie/backend_server/utils.py << EOF
# Copy and paste your OpenAI API Key
openai_api_key = "$OPENAI_API_KEY"
# Put your name
key_owner = "$OPENAI_API_NAME"

maze_assets_loc = "../../environment/frontend_server/static_dirs/assets"
env_matrix = f"{maze_assets_loc}/the_ville/matrix"
env_visuals = f"{maze_assets_loc}/the_ville/visuals"

fs_storage = "../../environment/frontend_server/storage"
fs_temp_storage = "../../environment/frontend_server/temp_storage"

collision_block_id = "32125"

# Verbose 
debug = True
EOF

cd /app/environment/frontend_server && python manage.py runserver $HOST:$PORT > /app/server_logs.txt 2>&1 &
sleep 5

cd /app/reverie/backend_server && python reverie.py