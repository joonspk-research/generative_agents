

# Generative Agents: Interactive Simulacra of Human Behavior 

<p align="center" width="100%">
<img src="cover.png" alt="Smallville" style="width: 80%; min-width: 300px; display: block; margin: auto;">
</p>

This repository accompanies our research paper titled "[Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)." It contains our core simulation module for  generative agents—computational agents that simulate believable human behaviors—and their game environment. Below, we document the steps for setting up the simulation environment on your local machine and for replaying the simulation as a demo animation.

## Datacenter Town: Launching the Project

This fork adds multi-provider LLM support (OpenAI, Anthropic, OpenAI-compatible endpoints), an 8-resident datacenter-proposal scenario on the existing Ville map, experiment logging, and runtime logging. All commands below are run from the repository root unless noted.

### The dashboard (start here)

The dashboard starts a run, watches it, and graphs where each resident stands on the datacenter over time. It replaces the two-terminal workflow in Steps 3–7 below — it launches the simulation process itself, so you do not need a second terminal.

Do Step 1 and Step 2 once (virtualenv, `utils.py` with your API key), then start the environment server and open the dashboard:

```bash
source .venv/bin/activate
cd environment/frontend_server
python manage.py runserver
```

Open **[http://localhost:8000/dashboard](http://localhost:8000/dashboard)**.

To launch a run, click **Start simulation** and fill in:

| Field | What to put |
|-------|-------------|
| **Continue from** | the saved run to branch off. `base_the_ville_datacenter_n8_private` for the datacenter scenario, or any earlier run to continue it |
| **Name for the new run** | a new name — letters, numbers, `-` and `_` only. Must not already exist |
| **Seed memories** | the whisper CSV that gives each resident their starting facts: `the_ville/agent_history_init_datacenter_n8_private.csv`. Leave empty when continuing a run that was already seeded |
| **Steps to run** | 1 step = 10 game seconds, so **8640 steps is one game day**. 0 starts the run without advancing it |
| **Auto-save every** | how often the run is checkpointed, in steps |
| **Spending cap for a run (USD)** | the run stops itself when API spend reaches this |

The page then shows the run's progress, token spend, each resident's stance line, and a live map. **Keep the tab open** — the map panel is what advances the simulation, so closing it or letting the machine sleep pauses the run. For multi-day runs on macOS, hold the machine awake:

```bash
caffeinate -dis
```

The stance chart marks conversations (▲), whispers (◆) and reflections (■); click a conversation marker to read the transcript. The gear/settings pane sets the defaults for autosave, spending cap, and how often every resident's stance is read (**Read every agent's stance every** — 360 steps is one game hour).

### Prerequisites
- macOS or Linux with **Python 3.11** (`python3.11 --version`). Do not use Python 3.14; the Django 2.2 stack does not install cleanly there.
- An API key for at least one LLM provider. Embeddings currently use OpenAI (or an OpenAI-compatible endpoint), so an OpenAI key is needed even when chatting through Anthropic.
- Chrome or Safari for the map UI.

### Step 1. Install dependencies (one time)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -r requirements.txt
python scripts/diag_deps.py   # every package should print a version, then "OK"
```

`requirements-legacy.txt` holds the original 2023 pin set and is only for historical Python 3.9 environments.

### Step 2. Configure `utils.py` (one time)

```bash
cp reverie/backend_server/utils.py.example reverie/backend_server/utils.py
```

Edit `reverie/backend_server/utils.py` (it is gitignored, so keys stay local):

| Setting | What to set |
|---------|-------------|
| `llm_provider` | `openai`, `anthropic`, or `openai_compatible` |
| `chat_model` | e.g. `gpt-4o`, or a Claude model name when using Anthropic |
| `embedding_model` | default `text-embedding-3-small` |
| `openai_api_key` / `anthropic_api_key` | keys for the providers you use |
| `openai_compatible_base_url` / `openai_compatible_api_key` | only for Together, OpenRouter, or a local server |
| `log_level` | `INFO` normally, `DEBUG` to see each agent's perceive/retrieve/plan/reflect/execute stages |

Leave the path settings (`fs_storage`, `maze_assets_loc`, etc.) as they are.

### Step 3. Start the environment server (terminal 1)

```bash
source .venv/bin/activate
cd environment/frontend_server
python manage.py runserver
```

Open [http://localhost:8000/](http://localhost:8000/) and confirm the page says the environment server is up. Leave this terminal running.

### Step 4. Start the simulation server (terminal 2)

```bash
source .venv/bin/activate
cd reverie/backend_server
python reverie.py
```

Answer the two prompts:

```
Enter the name of the forked simulation: base_the_ville_datacenter_n8
Enter the name of the new simulation: dc-run-1
```

The new simulation name must not already exist in `environment/frontend_server/storage/`; pick a fresh name for each run (e.g. `dc-run-2`).

### Step 5. Open the map

Go to [http://localhost:8000/simulator_home](http://localhost:8000/simulator_home) and keep the tab open. The backend only advances when this page is open, because the browser sends each step's agent positions to the backend.

### Step 6. Run the scenario

At the `Enter option:` prompt in terminal 2:

```
call -- load history the_ville/agent_history_init_datacenter_n8.csv
run 100
```

The first command seeds each resident's memories about the datacenter proposal and their relationships; run it once, right after forking. `run 100` simulates 100 steps (each step is 10 seconds of game time). You can repeat `run N` as often as you like.

Other useful commands:

| Command | Effect |
|---------|--------|
| `call -- whisper all ;; <text>` | Injects a news event into every resident's memory, e.g. `call -- whisper all ;; The council posted a summary of the datacenter proposal.` |
| `call -- whisper Maya Okonkwo ;; <text>` | Injects an event into one resident's memory |
| `call -- analysis Elena Chen` | Interviews a resident without saving anything to memory (type `end_convo` to stop) |
| `print all persona schedule` | Shows every resident's current plan |
| `save` | Saves progress and keeps the session open |
| `fin` | Saves and exits |
| `exit` | Exits and **deletes** the current simulation folder |

Residents: Maya Okonkwo (AI founder), Luis Hernandez (union electrician), Denise Brooks (business owner), Rachel Nguyen (teacher and parent), Tom Whitaker (long-term homeowner), Aisha Rahman (environmental advocate), Marcus Williams (community organizer), Elena Chen (utility planner).

### Step 7. Resume or replay a run
- **Resume:** start `reverie.py` again and enter the saved simulation name (e.g. `dc-run-1`) as the forked simulation, with a new target name (e.g. `dc-run-1b`).
- **Replay:** with the environment server running, open `http://localhost:8000/replay/dc-run-1/1/`.

### The datacenter map (`the_ville_datacenter`)
Stanford's planner only lets a resident choose a house or bedroom whose name contains that resident's last name (e.g. `Moreno family's house`). Instead of changing that logic, the datacenter base uses a copy of the Ville map, `the_ville_datacenter`, in which the homes are renamed after our residents (e.g. `Whitaker family's house`, `Nguyen family's house`, `Aisha Rahman's room`). The visuals are shared with `the_ville`; only the name data under `static_dirs/assets/the_ville_datacenter/matrix/` differs. The original Smallville simulations still use `the_ville`, unchanged.

- **Rebuild the map** (after editing `HOME_RENAMES` in `scripts/datacenter_map.py`): `python scripts/datacenter_map.py build-map`.
- **Move an older datacenter run onto the new map** (runs created before this map existed, e.g. `testing7b`): save the run, press Ctrl+C, then run `python scripts/datacenter_map.py migrate <sim_name>` and fork it into a new name. This renames the homes inside the run's saved memories and switches its `maze_name`.

### Where the outputs go
- **Experiment data:** `environment/frontend_server/storage/<sim>/experiment/` contains `run_manifest.json` (models, personas, scenario), `conversations.jsonl`, `events.jsonl` (history and whisper injections), `agent_snapshots.jsonl` (written every `snapshot_every_n_steps` steps and on save), and `outcomes.jsonl` (written on save).
- **Backend runtime log:** `reverie/backend_server/logs/datacenter-town.log`. It has step timing, per-agent actions, LLM call latency and failures, CLI commands, and every `print()` line (logger name `print`) and stderr line such as tracebacks (logger name `stderr`), all timestamped. Set `capture_prints = False` in `utils.py` to keep prints console-only.
- **Frontend runtime log:** `environment/frontend_server/logs/frontend.log`. It has Django startup, request lines (`"POST /update_environment/ ..."`), environment/movement handling in `translator/views.py`, and captured `print()`/stderr output. Set `FRONTEND_LOG_LEVEL=DEBUG` before `runserver` for more detail.
- Both logs rotate at 5 MB (five backups kept) and use timestamps with a UTC offset, so they can be lined up against each other.
- **Per-step state:** `storage/<sim>/movement/<step>.json` and `storage/<sim>/environment/<step>.json`.

### Troubleshooting
- **Map loads but agents never move:** make sure `reverie.py` is waiting at `Enter option:` after a `run` command and the `simulator_home` tab is open and in focus.
- **`chat_completion FAILED` in the logs:** check the API key and model name in `utils.py`; the traceback in `reverie/backend_server/logs/datacenter-town.log` shows the provider's error.
- **`ModuleNotFoundError` when starting Django:** the venv is not active, or dependencies were installed with the wrong Python. Re-run Step 1.
- **Rebuilding the 8-resident base simulation** (after editing personas in `scripts/build_datacenter_n8_base.py`): `python scripts/build_datacenter_n8_base.py`. The script is the source of truth for persona text, so make persona edits there rather than in the generated `scratch.json` files, or a rebuild will overwrite them.
- **`KeyError: 'none'` in `new_act_address`:** the run is on the old `the_ville` map, so a resident's home is hidden by the last-name filter. Migrate it as described in the datacenter map section above.

## <img src="https://joonsungpark.s3.amazonaws.com:443/static/assets/characters/profile/Klaus_Mueller.png" alt="Generative Klaus">   Running the Original Smallville Simulation 
The steps below come from the original repository and use the stock 3-agent Smallville base. Complete the install and `utils.py` configuration from the Datacenter Town section above first. To run a new simulation, you will need to concurrently start two servers: the environment server and the agent simulation server.

### Step 1. Starting the Environment Server
Again, the environment is implemented as a Django project, and as such, you will need to start the Django server. To do this, first navigate to `environment/frontend_server` (this is where `manage.py` is located) in your command line. Then run the following command:

    python manage.py runserver

Then, on your favorite browser, go to [http://localhost:8000/](http://localhost:8000/). If you see a message that says, "Your environment server is up and running," your server is running properly. Ensure that the environment server continues to run while you are running the simulation, so keep this command-line tab open! (Note: I recommend using either Chrome or Safari. Firefox might produce some frontend glitches, although it should not interfere with the actual simulation.)

### Step 2. Starting the Simulation Server
Open up another command line (the one you used in Step 1 should still be running the environment server, so leave that as it is). Navigate to `reverie/backend_server` and run `reverie.py`.

    python reverie.py
This will start the simulation server. A command-line prompt will appear, asking the following: "Enter the name of the forked simulation: ". To start a 3-agent simulation with Isabella Rodriguez, Maria Lopez, and Klaus Mueller, type the following:
    
    base_the_ville_isabella_maria_klaus
The prompt will then ask, "Enter the name of the new simulation: ". Type any name to denote your current simulation (e.g., just "test-simulation" will do for now).

    test-simulation
Keep the simulator server running. At this stage, it will display the following prompt: "Enter option: "

### Step 3. Running and Saving the Simulation
On your browser, navigate to [http://localhost:8000/simulator_home](http://localhost:8000/simulator_home). You should see the map of Smallville, along with a list of active agents on the map. You can move around the map using your keyboard arrows. Please keep this tab open. To run the simulation, type the following command in your simulation server in response to the prompt, "Enter option":

    run <step-count>
Note that you will want to replace `<step-count>` above with an integer indicating the number of game steps you want to simulate. For instance, if you want to simulate 100 game steps, you should input `run 100`. One game step represents 10 seconds in the game.


Your simulation should be running, and you will see the agents moving on the map in your browser. Once the simulation finishes running, the "Enter option" prompt will re-appear. At this point, you can simulate more steps by re-entering the run command with your desired game steps, exit the simulation without saving by typing `exit`, or save and exit by typing `fin`.

The saved simulation can be accessed the next time you run the simulation server by providing the name of your simulation as the forked simulation. This will allow you to restart your simulation from the point where you left off.

### Step 4. Replaying a Simulation
You can replay a simulation that you have already run simply by having your environment server running and navigating to the following address in your browser: `http://localhost:8000/replay/<simulation-name>/<starting-time-step>`. Please make sure to replace `<simulation-name>` with the name of the simulation you want to replay, and `<starting-time-step>` with the integer time-step from which you wish to start the replay.

For instance, by visiting the following link, you will initiate a pre-simulated example, starting at time-step 1:  
[http://localhost:8000/replay/July1_the_ville_isabella_maria_klaus-step-3-20/1/](http://localhost:8000/replay/July1_the_ville_isabella_maria_klaus-step-3-20/1/)

### Step 5. Demoing a Simulation
You may have noticed that all character sprites in the replay look identical. We would like to clarify that the replay function is primarily intended for debugging purposes and does not prioritize optimizing the size of the simulation folder or the visuals. To properly demonstrate a simulation with appropriate character sprites, you will need to compress the simulation first. To do this, open the `compress_sim_storage.py` file located in the `reverie` directory using a text editor. Then, execute the `compress` function with the name of the target simulation as its input. By doing so, the simulation file will be compressed, making it ready for demonstration.

To start the demo, go to the following address on your browser: `http://localhost:8000/demo/<simulation-name>/<starting-time-step>/<simulation-speed>`. Note that `<simulation-name>` and `<starting-time-step>` denote the same things as mentioned above. `<simulation-speed>` can be set to control the demo speed, where 1 is the slowest, and 5 is the fastest. For instance, visiting the following link will start a pre-simulated example, beginning at time-step 1, with a medium demo speed:  
[http://localhost:8000/demo/July1_the_ville_isabella_maria_klaus-step-3-20/1/3/](http://localhost:8000/demo/July1_the_ville_isabella_maria_klaus-step-3-20/1/3/)

### Tips
We've noticed that OpenAI's API can hang when it reaches the hourly rate limit. When this happens, you may need to restart your simulation. For now, we recommend saving your simulation often as you progress to ensure that you lose as little of the simulation as possible when you do need to stop and rerun it. Running these simulations, at least as of early 2023, could be somewhat costly, especially when there are many agents in the environment.

## <img src="https://joonsungpark.s3.amazonaws.com:443/static/assets/characters/profile/Maria_Lopez.png" alt="Generative Maria">   Simulation Storage Location
All simulations that you save will be located in `environment/frontend_server/storage`, and all compressed demos will be located in `environment/frontend_server/compressed_storage`. 

## <img src="https://joonsungpark.s3.amazonaws.com:443/static/assets/characters/profile/Sam_Moore.png" alt="Generative Sam">   Customization

There are two ways to optionally customize your simulations. 

### Author and Load Agent History
First is to initialize agents with unique history at the start of the simulation. To do this, you would want to 1) start your simulation using one of the base simulations, and 2) author and load agent history. More specifically, here are the steps:

#### Step 1. Starting Up a Base Simulation 
There are three base simulations included in the repository: `base_the_ville_datacenter_n8` (datacenter proposal, 8 agents), `base_the_ville_n25` with 25 agents, and `base_the_ville_isabella_maria_klaus` with 3 agents. Load one of the base simulations by following the steps until step 2 above. For the datacenter scenario, also see the **Datacenter Town** section above. 

#### Step 2. Loading a History File 
Then, when prompted with "Enter option: ", you should load the agent history by responding with the following command:

    call -- load history the_ville/<history_file_name>.csv
Note that you will need to replace `<history_file_name>` with the name of an existing history file. There are two history files included in the repo as examples: `agent_history_init_n25.csv` for `base_the_ville_n25` and `agent_history_init_n3.csv` for `base_the_ville_isabella_maria_klaus`. These files include semicolon-separated lists of memory records for each of the agents—loading them will insert the memory records into the agents' memory stream.

#### Step 3. Further Customization 
To customize the initialization by authoring your own history file, place your file in the following folder: `environment/frontend_server/static_dirs/assets/the_ville`. The column format for your custom history file will have to match the example history files included. Therefore, we recommend starting the process by copying and pasting the ones that are already in the repository.

### Create New Base Simulations
For a more involved customization, you will need to author your own base simulation files. The most straightforward approach would be to copy and paste an existing base simulation folder, renaming and editing it according to your requirements. This process will be simpler if you decide to keep the agent names unchanged. However, if you wish to change their names or increase the number of agents that the Smallville map can accommodate, you might need to directly edit the map using the [Tiled](https://www.mapeditor.org/) map editor.


## <img src="https://joonsungpark.s3.amazonaws.com:443/static/assets/characters/profile/Eddy_Lin.png" alt="Generative Eddy">   Authors and Citation 

**Authors:** Joon Sung Park, Joseph C. O'Brien, Carrie J. Cai, Meredith Ringel Morris, Percy Liang, Michael S. Bernstein

Please cite our paper if you use the code or data in this repository. 
```
@inproceedings{Park2023GenerativeAgents,  
author = {Park, Joon Sung and O'Brien, Joseph C. and Cai, Carrie J. and Morris, Meredith Ringel and Liang, Percy and Bernstein, Michael S.},  
title = {Generative Agents: Interactive Simulacra of Human Behavior},  
year = {2023},  
publisher = {Association for Computing Machinery},  
address = {New York, NY, USA},  
booktitle = {In the 36th Annual ACM Symposium on User Interface Software and Technology (UIST '23)},  
keywords = {Human-AI interaction, agents, generative AI, large language models},  
location = {San Francisco, CA, USA},  
series = {UIST '23}
}
```

## <img src="https://joonsungpark.s3.amazonaws.com:443/static/assets/characters/profile/Wolfgang_Schulz.png" alt="Generative Wolfgang">   Acknowledgements

We encourage you to support the following three amazing artists who have designed the game assets for this project, especially if you are planning to use the assets included here for your own project: 
* Background art: [PixyMoon (@_PixyMoon\_)](https://twitter.com/_PixyMoon_)
* Furniture/interior design: [LimeZu (@lime_px)](https://twitter.com/lime_px)
* Character design: [ぴぽ (@pipohi)](https://twitter.com/pipohi)

In addition, we thank Lindsay Popowski, Philip Guo, Michael Terry, and the Center for Advanced Study in the Behavioral Sciences (CASBS) community for their insights, discussions, and support. Lastly, all locations featured in Smallville are inspired by real-world locations that Joon has frequented as an undergraduate and graduate student---he thanks everyone there for feeding and supporting him all these years.


