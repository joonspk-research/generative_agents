"""
Reads where each agent stands on the datacenter, on a 0-100 rubric, so the
dashboard can graph how those positions move over the run.

The probe is an observer, not a participant. It reads memory itself and calls
no retrieval, so it cannot stamp last_accessed and asking an agent its
position every game hour does not change what that agent retrieves, plans or
reflects on afterwards. Otherwise the probe would reset the recency clock on
exactly the datacenter memories it read, and the graph would be measuring its
own interference.

Each reading also records the memories it was based on and the cosines that
chose them, which is what makes a move in the line explainable. Results go to
storage/<sim>/experiment/opinions.jsonl (see experiment_logger.py).

The evidence a reading is built from comes from two sources, selected
separately and merged in time order:

  memories       seq_event and seq_thought, by raw cosine to the stance
                 question across the whole pool, keeping only what is close
                 enough to be evidence about it, deduplicated by collapse()
                 and allocated over age bands (allocate).
  spoken lines   RESERVED_N slots for what the agent actually said, by latest
                 conversation and then cosine (select_utterances), read
                 straight off the chat nodes because seq_chat is not in
                 new_retrieve's pool.

Relevance selects rather than merely vetoing. new_retrieve's composite of
recency, relevance and importance stays exactly as it is for the agents' own
planning and reflection, where those are the right priorities; for an observer
asking one fixed question all run they are not. See probe for what the
composite cost when it chose the evidence.

The second source exists because the first one has the positions stripped out
of it. Measured over a full game day, 0.6% of pool events and 3.2% of pool
thoughts contain any verb of position, against 33% of the agent's own spoken
lines: a summary records that a conversation happened and what it covered,
not what anyone in it wanted. Rating on summaries alone converted being busy
with the datacenter into being in favour of it -- Maya Okonkwo, quoted
pushing the thing for the sake of her funding round, reads 40 on her
summaries and 85 once her own words are in front of the model, and Elena
Chen, who is paid to analyse the load and wants nothing either way, reads 85
on her summaries and 40 on her words.

Reasons a reading is deliberately withheld rather than guessed at, measured on
a full game day of eight agents:

  asleep_night        the agent is in bed for the whole hour, at night. A
  asleep_daytime      sleeping agent learns nothing about the datacenter, so
                      those hours can only repeat the last real reading or
                      wander; five of 41 consecutive asleep-to-asleep pairs
                      moved by ten points or more, one agent going 50, 70, 50,
                      70 without waking. Split because 28 agent-hours of it
                      were scheduled mid-day -- a planner defect, not a
                      night. See is_asleep and asleep_reason.
  no_relevant_memory  nothing in the pool clears RELEVANCE_FLOOR. The probe
                      abstained at a mean relevance of 0.39 and scored at a
                      mean of 0.60; below the floor the same evidence came
                      back as "none" on one hour and 70 on the next -- Marcus
                      Williams at 0.333 did exactly that six times against
                      three.
  no_memory           an agent that has not stepped has nothing to read.
  abstained           the model was asked and declined to place the agent.
  evaluator_invalid   the model was asked and never answered usably
                      (run_gpt_prompt_datacenter_stance).

A withheld reading is logged with a null score and a reason, not dropped. The
chart lifts the pen on a null (dashboard.html), so a gap is visible as a gap
instead of being interpolated through.
"""
import re

from persona.cognitive_modules.retrieve import cos_sim, extract_relevance
from persona.prompt_template.gpt_structure import get_embedding
from persona.prompt_template.run_gpt_prompt import (
  STANCE_QUESTION, STANCE_SCALE, STANCE_SCORING_VERSION,
  run_gpt_prompt_datacenter_stance)

# Memories each rating is based on, the same number a normal retrieval uses.
EVIDENCE_N = 30
# How many of the EVIDENCE_N slots are held for the agent's own spoken lines.
# They have to be reserved rather than won: see rank_utterances for why these
# lines lose a shared ranking every time.
RESERVED_N = 10

# Memory slots per age band, measured back from the probe's own clock. Ranking
# by relevance alone (see probe) has no time term in it at all, so on a long
# run the best EVIDENCE_N collapse onto whichever period the agent discussed
# the datacenter most intensely -- and the line then reports a position the
# agent has since moved off. Banding guarantees the prompt holds something
# from now and something from before, which is the least the model needs to
# answer what the prompt actually asks: where does this agent stand at the end
# of these memories. The taper weights the present without erasing the past.
# <limit> is the band's upper age in game hours; None is everything older.
BANDS = (("recent", 12, 8), ("mid", 36, 7), ("old", None, 5))

# Most statements an age band will take from a single timestamp. perceive.py
# writes one event per tick for a conversation that is still going and both
# participants perceive both sides, so a single chat arrives as a dozen
# near-identical lines; collapse() removes the ones that are textually the
# same, and this stops what survives -- the chat summary, a perceived event, a
# thought about it -- from crowding a band on its own.
PER_TIMESTAMP_N = 3

# Of the RESERVED_N quote slots, how many are held for the agent's latest
# conversations rather than won on relevance. Measured over a game day, one
# agent's quote block was byte-identical for 18 consecutive probes across 25
# game hours while they held two conversations that never reached a prompt:
# relevance alone has no reason to prefer what was just said, and a
# conversation the agent has just had is precisely what the graph exists to
# detect.
RECENT_UTTERANCE_N = 4

# Highest-scoring rejected candidates recorded per reading, so a reading can be
# read back against what it nearly used without storing the whole pool.
REJECTED_N = 5

# Hours counted as night when labelling a withheld asleep reading. A labelling
# convention only -- nothing is gated on it. See probe for why the two cases
# are worth telling apart.
NIGHT_FROM, NIGHT_TO = 22, 6

# Raw cosine, below which the model's answer stopped depending on the evidence.
# See the module docstring: 0.39 mean when abstaining against 0.59 when
# scoring, so the two populations separate cleanly either side of this.
RELEVANCE_FLOOR = 0.45

# perceive.py writes one event per perception tick for a conversation that is
# still going, and both participants perceive both sides of it, so a single
# chat arrives as a dozen near-identical lines that differ only in who the
# subject is. In the measured run these filled a mean of 19% of the prompt and
# a maximum of 80% of it, and they carry a summary rather than anything that
# was said -- the probe could see that an agent kept talking to opponents but
# never what any of them argued.
_CONVERSING = re.compile(r"^.*? is conversing about ", re.I)


def canonical(embedding_key):
  """The part of a statement that carries information, lowercased.

  Strips the "<someone> is conversing about " opener so that the same
  conversation seen from either side, and at every tick it ran for, collapses
  onto one entry.
  """
  return _CONVERSING.sub("", embedding_key or "").strip().lower()


def collapse(nodes):
  """Drops repeats of a statement the prompt already carries, keeping the
  first -- which, on retrieval's output, is the best-ranked one.

  Exact canonical matches only. Paraphrases that are merely similar are left
  in: deciding that two differently-worded thoughts say the same thing is a
  judgement the probe should not be making silently on the evidence it then
  rates.
  """
  seen, kept = set(), []
  for node in nodes:
    key = canonical(node.embedding_key)
    if key in seen:
      continue
    seen.add(key)
    kept += [node]
  return kept


def band_of(created, curr_time):
  """Which BANDS age band a statement falls in, at the probe's clock."""
  hours = (curr_time - created).total_seconds() / 3600
  for name, limit, _ in BANDS:
    if limit is None or hours <= limit:
      return name
  return BANDS[-1][0]


def allocate(ranked, curr_time, budget):
  """Fills <budget> evidence slots from <ranked>, best first, across BANDS.

  <ranked> comes in best-relevance-first and already deduplicated. Each band
  takes up to its own quota, and no single timestamp takes more than
  PER_TIMESTAMP_N.

  A band with nothing to put in it gives its slots back rather than wasting
  them: once every band has had its quota, the slots still free go to the best
  remaining candidates from any band, in the same order. So banding can only
  change which of the relevant memories are shown, never how many -- early in
  a run, when everything is in one band, the result is exactly the best
  <budget> by relevance. The per-timestamp cap holds through the spill too,
  or one conversation would take back the slots banding just denied it.

  Underfilling is the honest outcome when the cap or the pool runs out: on a
  measured game day the prompt held a mean of 5.8 statements against 20 slots,
  so supply, not allocation, is the usual constraint.

  Returns (kept, rejected, occupancy): the nodes to show, [(node, reason)] for
  the ones that lost a slot, and the band counts that resulted.
  """
  quota = {name: n for name, _, n in BANDS}
  occupancy = {name: 0 for name in quota}
  at_stamp = {}
  kept, deferred = [], []

  def take(node, band):
    occupancy[band] += 1
    at_stamp[node.created] = at_stamp.get(node.created, 0) + 1
    kept.append(node)

  for node in ranked:
    band = band_of(node.created, curr_time)
    if len(kept) >= budget:
      deferred += [(node, "budget_full")]
    elif at_stamp.get(node.created, 0) >= PER_TIMESTAMP_N:
      deferred += [(node, "timestamp_cap")]
    elif occupancy[band] >= quota[band]:
      deferred += [(node, "band_full")]
    else:
      take(node, band)

  rejected = []
  for node, reason in deferred:
    band = band_of(node.created, curr_time)
    if (reason == "band_full" and len(kept) < budget
        and at_stamp.get(node.created, 0) < PER_TIMESTAMP_N):
      take(node, band)
    else:
      rejected += [(node, reason)]
  return kept, rejected, occupancy


def is_asleep(persona):
  """Whether the agent is in bed for the whole game hour this reading covers.

  The hour, not the instant. The probe fires at the top of the hour, before
  the day's next action has been installed, so reading act_description alone
  withheld a reading from an agent who woke twenty minutes later: 28 of 177
  asleep withholdings over a measured game day had that agent active
  elsewhere within the same game hour.

  f_daily_schedule is the whole decomposed day as [task, minutes] pairs and
  get_f_daily_schedule_index already takes a forward look-ahead in minutes
  (scratch.py), so the coming hour can be read off the schedule without
  waiting for it to arrive. Withheld only if every task in that hour is a
  sleep task; one non-sleep task makes the hour awake and the reading is
  taken.

  Read-only, like the rest of the probe: this looks the schedule up, it does
  not advance or revise it.

  Falls back to the current action before the first plan exists, when
  f_daily_schedule is still empty -- the same guard dashboard_bridge.py uses.
  The clock is no use either way, because agents keep their own schedules and
  revise_identity rewrites them nightly: there is no hour at which the whole
  cast is reliably asleep or reliably up.
  """
  def sleeping(task):
    return "sleep" in (task or "").lower()

  schedule = getattr(persona.scratch, "f_daily_schedule", None)
  if not schedule:
    return sleeping(persona.scratch.act_description)
  # Every ten minutes of the hour, so a task shorter than the hour is still
  # seen. Indices repeat for a long task and run off the end late in the day.
  reached = {persona.scratch.get_f_daily_schedule_index(advance=minute)
             for minute in range(0, 60, 10)}
  tasks = [schedule[i][0] for i in sorted(reached) if i < len(schedule)]
  if not tasks:
    return sleeping(persona.scratch.act_description)
  return all(sleeping(task) for task in tasks)


def asleep_reason(curr_time):
  """Which asleep label a withheld reading carries.

  Night sleep is the agent behaving normally and the reading is simply not
  available. Daytime sleep is a planning defect: over a measured game day 28
  agent-hours were scheduled mid-day sleep, 13 of them one agent's, and
  burying those in the same label as 3 a.m. hides a bug in the planner behind
  an expected gap in the graph.
  """
  if curr_time is None:
    return "asleep_night"
  hour = curr_time.hour
  night = hour >= NIGHT_FROM or hour < NIGHT_TO
  return "asleep_night" if night else "asleep_daytime"


_EMBEDDINGS = {}


def embed(text):
  """get_embedding with an in-process cache, keyed by the text itself.

  Deliberately not cached into persona.a_mem.embeddings, which is where the
  simulation keeps its own: that dict is written out with the agent, so
  putting the probe's embeddings in it would make the observer mutate the
  state it is observing -- the same invariant touch=False protects. The cost
  of keeping it in memory instead is re-embedding once per process, a few
  hundred short strings for a game day of eight agents.
  """
  if text not in _EMBEDDINGS:
    _EMBEDDINGS[text] = get_embedding(text)
  return _EMBEDDINGS[text]


def own_utterances(persona):
  """What this agent actually said in its conversations, newest first.

  Chat nodes carry the whole exchange in <filling>, as [speaker, line] pairs,
  and seq_chat is not in new_retrieve's candidate pool (retrieve.py:232) --
  Stanford left a note on the line above it that the raw conversation could
  be retrieved too, "but for now". So these lines are unreachable by normal
  retrieval, and the probe reads them itself rather than widening the pool:
  widening it would change what every agent retrieves while planning and
  reflecting, which is a change to the simulation and not to the observer.

  This matters because the pool the probe can otherwise see has had the
  positions stripped out of it. Measured over a full game day, 0.6% of pool
  events and 3.2% of pool thoughts contain any verb of position, against
  33% of the agent's own spoken lines: the summaries record that a
  conversation happened and what it covered, not what anyone wanted.

  Only this agent's own turns. What was said to them is already in the pool
  as a perceived event, and taking both sides would double the tokens to
  re-import the near-duplicate problem collapse() exists to remove.

  Returns [(created, line)], deduplicated by line. <created> is the parent
  chat node's timestamp, so every turn of one conversation shares it -- the
  resolution here is per conversation, not per turn.
  """
  seen, out = set(), []
  for node in persona.a_mem.seq_chat:
    for turn in node.filling or []:
      if not isinstance(turn, (list, tuple)) or len(turn) != 2:
        continue
      speaker, line = turn
      line = (line or "").strip()
      if speaker != persona.scratch.name or not line:
        continue
      if line.lower() in seen:
        continue
      seen.add(line.lower())
      out += [(node.created, line)]
  return out


def rank_utterances(utterances, n):
  """The n spoken lines closest to the stance question, by raw cosine.

  Relevance alone, where new_retrieve also uses recency and importance, for
  two reasons. There is no per-line recency or importance to use: both would
  have to be inherited from the parent chat node, which is one value for
  every turn of a conversation and so cannot order them. And because these
  lines hold reserved slots rather than competing for ranked ones, there is
  nothing for a second component to trade off against.

  Raw cosine, not new_retrieve's normalized score, because the absolute
  values are the finding. Measured over a game day, own utterances score a
  median 0.24 against the stance question where the statements already in the
  prompt score 0.51 -- the pool's statements are model-written summaries in
  the same register as the question, while an utterance is conversational and
  spends most of its tokens on greeting and hedging. Only 61 of 431
  utterances outscored the weakest statement already in the prompt, and for
  one agent none of 97 did. In a shared ranking these lines lose every slot,
  every time, which is why they get reserved ones instead.

  Cosine is no judge of whether a line states a position: 35% of the top ten
  do, against a 33% base rate, which is chance. It is a good judge of whether
  the line is about the datacenter at all -- 78% of the top ten, against 29%
  across all utterances, 34% for the most recent ten and 26% for a random
  ten. Topicality is the job being asked of it. The position density comes
  from the base rate, which is fifty times the pool's.

  Ranking by relevance and not recency is also what keeps a trajectory
  readable. Recency as a decaying weight tracks what the agent last thought
  about, so an agent who argued a position and then got busy would have its
  evidence fade and its line drift toward the middle -- reporting a drop in
  attention as a change of mind. Over a long run the risk runs the other way,
  the top n collapsing onto whichever week the agent talked about this most,
  so probe() records the time span these lines were drawn from.
  """
  question = embed(STANCE_QUESTION)
  ranked = sorted(((cos_sim(embed(line), question), created, line)
                   for created, line in utterances),
                  key=lambda row: row[0], reverse=True)
  return [(created, line) for _, created, line in ranked[:n]]


def select_utterances(utterances, n):
  """The n spoken lines to quote: the latest conversations, then the closest.

  RECENT_UTTERANCE_N slots go to the agent's most recent conversations and the
  rest to rank_utterances across everything earlier. Relevance alone is blind
  to a conversation having just happened, which is how one agent's quote block
  stayed byte-identical for 18 probes across two conversations it never
  showed (see RECENT_UTTERANCE_N).

  The grain is the conversation, not the turn. own_utterances inherits every
  line's timestamp from the parent chat node, so all of one conversation's
  turns share a <created> and there is nothing finer to rank them by -- which
  is also why the recent slots are filled in dialogue order rather than by
  cosine. Ordering them by relevance put a reply ahead of the line it was
  replying to.

  Returns [(created, line)] oldest first, dialogue order kept within a
  conversation. probe merges these with the memories using a stable sort on
  <created> alone, so that order survives into the prompt.
  """
  position = {}
  for i, pair in enumerate(utterances):
    position.setdefault(pair, i)

  # own_utterances walks seq_chat newest node first, so consecutive runs of one
  # timestamp are one conversation, newest conversation first.
  conversations = []
  for pair in utterances:
    if not conversations or conversations[-1][0] != pair[0]:
      conversations += [(pair[0], [])]
    conversations[-1][1].append(pair)

  recent = []
  for _, lines in conversations:
    if len(recent) >= min(RECENT_UTTERANCE_N, n):
      break
    recent += lines[:min(RECENT_UTTERANCE_N, n) - len(recent)]

  taken = set(recent)
  earlier = [pair for pair in utterances if pair not in taken]
  # Asking rank_utterances to rank nothing still embeds the question, which is
  # an API call for an agent who has not spoken, or whose every line fit in
  # the recent slots.
  chosen = recent + (rank_utterances(earlier, n - len(recent)) if earlier else [])
  return sorted(chosen, key=lambda pair: (pair[0], position[pair]))


def pool_relevance(persona):
  """Raw cosine from every retrievable memory to the stance question.

  new_retrieve min-max normalizes relevance within each call
  (retrieve.py:244), so whichever node it ranks first scores 1.0 whether its
  true similarity was 0.8 or 0.1. There is no absolute floor anywhere in the
  ranking, and the rescaled score cannot supply one because it is relative to
  whatever candidates happened to exist. extract_relevance returns the raw
  cosines, from before that rescaling.

  Same node set and same focal point as the probe's retrieval, so these are
  the cosines that ranking was built from. {} when the agent has no memory.
  """
  nodes = [n for n in persona.a_mem.seq_event + persona.a_mem.seq_thought
           if "idle" not in n.embedding_key]
  return extract_relevance(persona, nodes, STANCE_QUESTION) if nodes else {}


def measure_relevance(raw, retrieved):
  """How close the prompt's memories actually are to the stance question.

  Takes pool_relevance's raw cosines and the nodes the prompt ended up with.

  Returns {"shown", "best"}: the closest memory the model was actually given,
  and the closest one in the whole memory stream. "shown" is what says whether
  a reading had anything to work from at all, and is what RELEVANCE_FLOOR is
  applied to.

  The gap between the two used to say whether a relevant memory existed and
  lost its place to recency and importance, which new_retrieve weights equally
  with relevance (gw = [1, 1, 1]). It did: on a measured game day 22 of 31
  withheld readings held a memory above the floor that the composite ranking
  never offered, so the probe reported having nothing relevant to read while
  the agent's single most relevant memory sat in the pool.

  Now that probe selects by relevance (see probe), the pool's closest memory is
  the global maximum and so ranks first overall, first in its band and first at
  its timestamp -- no allocation can evict it. So the gap closes to zero
  whenever anything clears the floor at all, and these two numbers agreeing is
  the invariant to check rather than a finding about EVIDENCE_N.
  """
  if not raw:
    return {"shown": None, "best": None}
  shown = [raw[node.node_id] for node in retrieved if node.node_id in raw]
  # cos_sim hands back numpy floats, which land in the log file as whatever
  # json.dumps makes of them.
  return {"shown": float(max(shown)) if shown else None,
          "best": float(max(raw.values()))}


def quoted_span(quoted):
  """The window the quoted lines were drawn from, for the log.

  Instrumentation, not a gate. Ranking spoken lines by relevance alone is
  safe while a run is short -- measured over one game day the top ten spanned
  very nearly the full waking range for every agent -- but the top n of a
  year's conversations would be drawn from whichever week the agent argued
  about this most, and the reading would then be of a position it had since
  moved off. Two agents already tilt early, 2 of 10 and 1 of 10 in the later
  half of their day, so the failure mode is visible rather than theoretical.
  Recording the span means a multi-day run shows it collapsing instead of
  having to be guessed at.
  """
  if not quoted:
    return {"n": 0, "first": None, "last": None}
  created = sorted(created for created, _ in quoted)
  return {"n": len(quoted),
          "first": created[0].strftime("%Y-%m-%d %H:%M:%S"),
          "last": created[-1].strftime("%Y-%m-%d %H:%M:%S")}


def probe(persona, with_metadata=False):
  """Reads one persona's position on the datacenter.

  Returns (score, rationale, evidence, relevance, withheld, quoted). <score>
  is 0 to STANCE_SCALE, or None when the reading was withheld or the model
  gave no usable rating; <evidence> is the node ids the rating was based on;
  <relevance> is measure_relevance's reading of how much those nodes had to do
  with the question; <withheld> names the reason a null score is null, or is
  None when the model was actually asked; and <quoted> is quoted_span's record
  of the spoken lines that went in beside the memories.

  The evidence block is built from two sources that are selected separately
  and then merged in time order: the retrievable memories, by raw cosine to
  the stance question across the whole pool and then allocated over age bands
  (allocate), and the agent's own spoken lines, by latest conversation and
  cosine (select_utterances). They cannot share one ranking -- see
  rank_utterances. RESERVED_N slots go to the spoken lines when there are that
  many, and the reservation is a ceiling rather than a quota -- an agent who
  has said less gives the unused slots back to the memories, and early in a
  run, before anyone has spoken, the prompt is exactly what it was before.

  Memories are selected by relevance alone, and not by new_retrieve's
  composite of recency, relevance and importance. The composite is right for
  the agent, whose own planning and reflection still use it untouched; it is
  wrong for an observer. new_retrieve min-max normalizes relevance within each
  call, so it cannot say whether anything is on topic, and the raw cosine used
  to be applied afterwards as a veto -- able to reject what the composite
  offered but never to nominate what it missed. The probe asks one fixed
  question all run, so closeness to that question is the whole of what it
  needs. Measured over a game day: one agent's reading rested on 5 of its
  1,679 memories, five of eight agents sat on a single anchor memory for the
  whole run, and 22 of 31 withheld readings had a memory above the floor that
  the composite never offered. Dropping the composite also drops the second of
  the two question embeddings each reading used to pay for, since
  pool_relevance computes the same cosines.

  Every reading records the selection that produced it, under "selection":
  the cosine and band of each statement shown, the cosine of each line quoted,
  the highest-scoring candidates that lost a slot and why, and the band
  occupancy that resulted. pool_relevance already computes all of it and used
  to discard everything but two numbers, so this costs no extra call and is
  what makes a reading re-derivable after the fact.
  """
  def result(score, rationale, evidence, relevance, withheld, quoted,
             category=None, conditions=None, selection=None):
    if with_metadata:
      return {"score": score, "rationale": rationale, "evidence": evidence,
              "relevance": relevance, "withheld": withheld, "quoted": quoted,
              "category": category, "conditions": conditions or [],
              "selection": selection or {},
              "scoring_version": STANCE_SCORING_VERSION}
    return score, rationale, evidence, relevance, withheld, quoted

  if is_asleep(persona):
    # Before retrieval, which embeds the question and so costs a call.
    return result(None, f"{persona.scratch.name} is asleep.", [],
            {"shown": None, "best": None},
            asleep_reason(persona.scratch.curr_time), quoted_span([]))

  pool = [node for node in persona.a_mem.seq_event + persona.a_mem.seq_thought
          if "idle" not in node.embedding_key]
  if not pool:
    return result(None, "No retrievable memories yet.", [],
                  {"shown": None, "best": None}, "no_memory", quoted_span([]))

  quoted = select_utterances(own_utterances(persona), RESERVED_N)

  raw = pool_relevance(persona)
  # A statement that is not close enough to the datacenter is not evidence
  # about the datacenter. Measured over the last eight prompts of a game day,
  # 35% of the 240 statements sat below the floor and 14% below 0.35 -- 27 of
  # Luis Hernandez's 30, and 21 of Rachel Nguyen's with one at 0.108. Dropping
  # them can leave a prompt short of EVIDENCE_N, which is the honest outcome:
  # there were not that many relevant memories. Sorting after the filter, and
  # over a pool in insertion order, keeps the result stable without a tiebreak.
  ordered = sorted(pool, key=lambda node: -raw.get(node.node_id, 0.0))
  above = collapse([node for node in ordered
                    if raw.get(node.node_id, 0.0) >= RELEVANCE_FLOOR])
  retrieved, rejected, occupancy = allocate(
    above, persona.scratch.curr_time, EVIDENCE_N - len(quoted))

  evidence = [node.node_id for node in retrieved]
  relevance = measure_relevance(raw, retrieved)
  rejected += [(node, "below_floor") for node in ordered
               if raw.get(node.node_id, 0.0) < RELEVANCE_FLOOR]
  question = embed(STANCE_QUESTION)
  selection = {
    "memories": [{"id": node.node_id,
                  "cos": round(float(raw[node.node_id]), 4),
                  "band": band_of(node.created, persona.scratch.curr_time),
                  "created": node.created.strftime("%Y-%m-%d %H:%M:%S")}
                 for node in retrieved],
    # The line itself is already in the transcript; the cosine is the part
    # that was computed and thrown away, and it is what says whether a floor
    # on spoken lines could ever have been measured.
    "quoted": [{"cos": round(float(cos_sim(embed(line), question)), 4),
                "created": created.strftime("%Y-%m-%d %H:%M:%S")}
               for created, line in quoted],
    "rejected": [{"id": node.node_id,
                  "cos": round(float(raw.get(node.node_id, 0.0)), 4),
                  "reason": reason}
                 for node, reason in sorted(
                   rejected,
                   key=lambda row: -raw.get(row[0].node_id, 0.0))[:REJECTED_N]],
    "bands": occupancy,
  }

  shown = relevance["shown"]
  if shown is None:
    # Asking anyway produces a number, and that number is the prompt's opinion
    # of the name rather than the agent's opinion of the datacenter. Spoken
    # lines are not allowed to lift this gate even when there are ten of them:
    # they sit at a median cosine of 0.24 against 0.51 for the statements
    # already in a prompt, only 61 of 431 outscored the weakest statement
    # already there and for one agent none of 97 did, so RELEVANCE_FLOOR
    # cannot be applied to them and no separate floor has been measured.
    # "selection" now carries their cosines, which is what would measure one.
    best = relevance["best"]
    return result(None, f"Nothing in {persona.scratch.name}'s memory is close "
            f"enough to the datacenter to rate"
            f"{'' if best is None else f' (relevance {best:.2f})'}.",
            evidence, relevance, "no_relevant_memory", quoted_span(quoted),
            selection=selection)

  # Oldest first, each line dated, memories and spoken lines interleaved.
  # Selection returns these ranked by relevance, and a shuffled undated list is
  # unreadable as a trajectory: the model cannot tell what this agent thought
  # an hour ago from what it thought yesterday, which is the one distinction
  # the graph exists to show. The sort is stable and select_utterances hands
  # back its lines in dialogue order, so turns of one conversation stay in the
  # order they were spoken. Spoken lines are marked as spoken so the prompt
  # can tell the model to weigh this person's own words above a summary of a
  # conversation they were in.
  lines = [(node.created, node.embedding_key) for node in retrieved]
  lines += [(created, f'{persona.scratch.name} said: "{line}"')
            for created, line in quoted]
  statements = "\n".join(
    f'{created.strftime("%B %d, %H:%M")} -- {text}'
    for created, text in sorted(lines, key=lambda row: row[0]))
  rating = run_gpt_prompt_datacenter_stance(
    persona, statements, with_metadata=True)[0]
  return result(rating["score"], rating["rationale"], evidence, relevance,
                rating["withheld"], quoted_span(quoted), rating["category"],
                rating["conditions"], selection)
