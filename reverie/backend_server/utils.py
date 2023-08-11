'''
Default version of Reverie configuration file.

This sets various paths relative to this file.
'''

import os

this_dir = os.path.abspath(os.path.dirname(__file__))
environment_loc = os.path.abspath(f"{this_dir}/../../environment/")

# To the user: set with your OpenAI API key.
openai_api_key=""
key_owner=""

maze_assets_loc = f"{environment_loc}/frontend_server/static_dirs/assets"
env_matrix = f"{maze_assets_loc}/the_ville/matrix"
env_visuals = f"{maze_assets_loc}/the_ville/visuals"

fs_storage = f"{environment_loc}/frontend_server/storage"
fs_temp_storage = f"{environment_loc}/frontend_server/temp_storage"

collision_block_id = "32125"

# Verbose 
debug = True

