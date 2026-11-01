"""
Wrapper functions for calling LLM APIs (multi-provider).

Preserves the historical function names used across cognitive modules.
"""
import json
import time

from utils import *
from llm.client import chat_completion, get_embedding_vector, extract_json_output


def temp_sleep(seconds=0.1):
  time.sleep(seconds)


def _user_messages(prompt):
  return [{"role": "user", "content": prompt}]


def ChatGPT_single_request(prompt):
  temp_sleep()
  try:
    return chat_completion(_user_messages(prompt), model=chat_model)
  except Exception as e:
    print(f"ChatGPT ERROR: {e}")
    return "ChatGPT ERROR"


def GPT4_request(prompt):
  temp_sleep()
  try:
    model = globals().get("gpt4_model", chat_model)
    return chat_completion(_user_messages(prompt), model=model)
  except Exception as e:
    print(f"ChatGPT ERROR: {e}")
    return "ChatGPT ERROR"


def ChatGPT_request(prompt, temperature=None):
  # temperature=None leaves the chat_completion default in place, which is what
  # every caller that passes a gpt_param dict has always relied on.
  try:
    kwargs = {} if temperature is None else {"temperature": temperature}
    return chat_completion(_user_messages(prompt), model=chat_model, **kwargs)
  except Exception as e:
    print(f"ChatGPT ERROR: {e}")
    return "ChatGPT ERROR"


def GPT4_safe_generate_response(prompt,
                                example_output,
                                special_instruction,
                                repeat=3,
                                fail_safe_response="error",
                                func_validate=None,
                                func_clean_up=None,
                                verbose=False):
  prompt = 'GPT-3 Prompt:\n"""\n' + prompt + '\n"""\n'
  prompt += f"Output the response to the prompt above in json. {special_instruction}\n"
  prompt += "Example output json:\n"
  prompt += '{"output": "' + str(example_output) + '"}'

  if verbose:
    print("CHAT GPT PROMPT")
    print(prompt)

  for i in range(repeat):
    try:
      curr_gpt_response = extract_json_output(GPT4_request(prompt).strip())
      if func_validate(curr_gpt_response, prompt=prompt):
        return func_clean_up(curr_gpt_response, prompt=prompt)
      if verbose:
        print("---- repeat count: \n", i, curr_gpt_response)
        print(curr_gpt_response)
        print("~~~~")
    except Exception:
      pass

  return False


def ChatGPT_safe_generate_response(prompt,
                                   example_output,
                                   special_instruction,
                                   repeat=3,
                                   fail_safe_response="error",
                                   func_validate=None,
                                   func_clean_up=None,
                                   verbose=False,
                                   temperature=None):
  prompt = '"""\n' + prompt + '\n"""\n'
  prompt += f"Output the response to the prompt above in json. {special_instruction}\n"
  prompt += "Example output json:\n"
  prompt += (json.dumps({"output": example_output}) if isinstance(example_output, dict)
             else '{"output": "' + str(example_output) + '"}')

  if verbose:
    print("CHAT GPT PROMPT")
    print(prompt)

  for i in range(repeat):
    try:
      curr_gpt_response = extract_json_output(
                            ChatGPT_request(prompt, temperature).strip())
      if func_validate(curr_gpt_response, prompt=prompt):
        return func_clean_up(curr_gpt_response, prompt=prompt)
      if verbose:
        print("---- repeat count: \n", i, curr_gpt_response)
        print(curr_gpt_response)
        print("~~~~")
    except Exception:
      pass

  return False


def ChatGPT_safe_generate_response_OLD(prompt,
                                       repeat=3,
                                       fail_safe_response="error",
                                       func_validate=None,
                                       func_clean_up=None,
                                       verbose=False):
  if verbose:
    print("CHAT GPT PROMPT")
    print(prompt)

  for i in range(repeat):
    try:
      curr_gpt_response = ChatGPT_request(prompt).strip()
      if func_validate(curr_gpt_response, prompt=prompt):
        return func_clean_up(curr_gpt_response, prompt=prompt)
      if verbose:
        print(f"---- repeat count: {i}")
        print(curr_gpt_response)
        print("~~~~")
    except Exception:
      pass
  print("FAIL SAFE TRIGGERED")
  return fail_safe_response


def GPT_request(prompt, gpt_parameter):
  """
  Legacy Completions-style entry point. Now routes through chat completions
  using the configured chat_model (davinci engines are ignored).
  """
  temp_sleep()
  try:
    temperature = gpt_parameter.get("temperature", 0.7)
    max_tokens = gpt_parameter.get("max_tokens", 150)
    stop = gpt_parameter.get("stop")
    return chat_completion(
      _user_messages(prompt),
      model=chat_model,
      temperature=temperature,
      max_tokens=max_tokens,
      stop=stop,
    )
  except Exception as e:
    print(f"TOKEN LIMIT EXCEEDED / LLM ERROR: {e}")
    return "TOKEN LIMIT EXCEEDED"


def generate_prompt(curr_input, prompt_lib_file):
  if type(curr_input) == type("string"):
    curr_input = [curr_input]
  curr_input = [str(i) for i in curr_input]

  f = open(prompt_lib_file, "r")
  prompt = f.read()
  f.close()
  for count, i in enumerate(curr_input):
    prompt = prompt.replace(f"!<INPUT {count}>!", i)
  if "<commentblockmarker>###</commentblockmarker>" in prompt:
    prompt = prompt.split("<commentblockmarker>###</commentblockmarker>")[1]
  return prompt.strip()


def safe_generate_response(prompt,
                           gpt_parameter,
                           repeat=5,
                           fail_safe_response="error",
                           func_validate=None,
                           func_clean_up=None,
                           verbose=False):
  if verbose:
    print(prompt)

  for i in range(repeat):
    curr_gpt_response = GPT_request(prompt, gpt_parameter)
    if func_validate(curr_gpt_response, prompt=prompt):
      return func_clean_up(curr_gpt_response, prompt=prompt)
    if verbose:
      print("---- repeat count: ", i, curr_gpt_response)
      print(curr_gpt_response)
      print("~~~~")
  return fail_safe_response


def get_embedding(text, model=None):
  text = text.replace("\n", " ")
  if not text:
    text = "this is blank"
  emb_model = model or globals().get("embedding_model", "text-embedding-3-small")
  return get_embedding_vector(text, model=emb_model)


if __name__ == '__main__':
  gpt_parameter = {"engine": "text-davinci-003", "max_tokens": 50,
                   "temperature": 0, "top_p": 1, "stream": False,
                   "frequency_penalty": 0, "presence_penalty": 0,
                   "stop": ['"']}
  curr_input = ["driving to a friend's house"]
  prompt_lib_file = "prompt_template/test_prompt_July5.txt"
  prompt = generate_prompt(curr_input, prompt_lib_file)

  def __func_validate(gpt_response, prompt=None):
    if len(gpt_response.strip()) <= 1:
      return False
    if len(gpt_response.strip().split(" ")) > 1:
      return False
    return True

  def __func_clean_up(gpt_response, prompt=None):
    return gpt_response.strip()

  output = safe_generate_response(prompt,
                                  gpt_parameter,
                                  5,
                                  "rest",
                                  __func_validate,
                                  __func_clean_up,
                                  True)
  print(output)
