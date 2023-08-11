import os
from dotenv import load_dotenv

load_dotenv()

# Copy and paste your OpenAI API Key
openai_api_key = os.environ.get('OPENAI_API_KEY')
# Put your name
key_owner = os.environ.get('KEY_OWNER')


maze_assets_loc = "../../environment/frontend_server/static_dirs/assets"
env_matrix = f"{maze_assets_loc}/the_ville/matrix"
env_visuals = f"{maze_assets_loc}/the_ville/visuals"

fs_storage = "../../environment/frontend_server/storage"
fs_temp_storage = "../../environment/frontend_server/temp_storage"

collision_block_id = "32125"

# Verbose 
debug = True