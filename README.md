
# Generative Agents
## Introduction 
Generative Agents: Interactive Simulacra of Human Behavior
This is the core simulation module for generative agents 

## Setup 
download everything in the requirements  

utils.py
```
# Copy and paste your OpenAI API Key
openai_api_key = "<Your OpenAI API>"
# Put your name
key_owner = "<Name>"

maze_assets_loc = "../../environment/frontend_server/static_dirs/assets"
env_matrix = f"{maze_assets_loc}/the_ville/matrix"
env_visuals = f"{maze_assets_loc}/the_ville/visuals"

fs_storage = "../../environment/frontend_server/storage"
fs_temp_storage = "../../environment/frontend_server/temp_storage"

collision_block_id = "32125"

# Verbose 
debug = True
```


## How to run a new simulation 
start your django server 

- python manage.py runserver
- travel to http://localhost:8000/simulator_home
	- This has your simulation frontend running. This always have to be running

open reverie.py 
rs = ReverieServer("July1_the_ville_isabella_maria_klaus-step-3-11", 
                     "July1_the_ville_isabella_maria_klaus-step-3-12") 
you need to input sim_code there... 
they should match the folder names in the storage file 
if you are creating a new sim, the latter is the target location, the former is the source sim

initialize memory via whisper

save. 
python reverie.py 
run < step count>

save the simulation by typing fin... 
I suggest saving because sometimes a prompt fails, or OpenAI hangs... 

## How to quickly replay a simulation (in testing) 
http://localhost:8000/replay/July1_the_ville_isabella_maria_klaus-step-2-7/1/

## How to demo a simulation

compress_sim_storage 