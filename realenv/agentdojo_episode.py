"""One AgentDojo episode (free simulated tool environment) driven by a local LLM
served by Ollama through its OpenAI-compatible API. Returns the oracle labels:
security = True means the injection task succeeded (a committed violation per
AgentDojo's post-state check), utility = True means the user task succeeded.

Randomness: temperature sampling with a per-episode seed (Ollama honours `seed`),
so an episode is a reproducible function of (task pair, attack, seed).
"""

import json
import sys
import time

import openai

from agentdojo.agent_pipeline import AgentPipeline, InitQuery, SystemMessage, ToolsExecutionLoop, ToolsExecutor
from agentdojo.agent_pipeline.agent_pipeline import load_system_message
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.task_suite.load_suites import get_suite

OLLAMA = "http://127.0.0.1:11434/v1"


class SeededOpenAILLM(OpenAILLM):
    """OpenAILLM with temperature > 0 and a per-episode seed."""

    def __init__(self, client, model, temperature, seed):
        super().__init__(client, model, temperature=temperature)
        self.seed = seed

    def query(self, query, runtime, env=None, messages=(), extra_args={}):
        orig = self.client.chat.completions.create

        def create(**kw):
            kw["seed"] = self.seed
            return orig(**kw)
        self.client.chat.completions.create = create
        try:
            return super().query(query, runtime, env, messages, extra_args) if env is not None \
                else super().query(query, runtime, messages=messages, extra_args=extra_args)
        finally:
            self.client.chat.completions.create = orig


def build_pipeline(model, temperature, seed, max_iters=6):
    client = openai.OpenAI(base_url=OLLAMA, api_key="ollama", timeout=600)
    llm = SeededOpenAILLM(client, model, temperature, seed)
    system = load_system_message(None)
    if model.startswith("qwen3"):                  # Qwen3 soft switch: non-thinking mode (thinking took up to
        system += "\n/no_think"                    # 25 min per episode on CPU; see results/raw/*thinking*)
    pipe = AgentPipeline([SystemMessage(system), InitQuery(), llm,
                          ToolsExecutionLoop([ToolsExecutor(), llm], max_iters=max_iters)])
    pipe.name = f"local-{model}"   # "local" lets AgentDojo attacks address it as "Local model"
    return pipe


def run_episode(suite_name, user_task_id, injection_task_id, attack_name, model, seed,
                temperature=0.7, version="v1.2.1"):
    suite = get_suite(version, suite_name)
    pipe = build_pipeline(model, temperature, seed)
    attack = load_attack(attack_name, suite, pipe)
    user_task = suite.get_user_task_by_id(user_task_id)
    inj_task = suite.get_injection_task_by_id(injection_task_id)
    injections = attack.attack(user_task, inj_task)
    t0 = time.time()
    utility, security = suite.run_task_with_pipeline(pipe, user_task, inj_task, injections)
    return {"suite": suite_name, "user_task": user_task_id, "injection_task": injection_task_id,
            "attack": attack_name, "model": model, "seed": seed, "temperature": temperature,
            "violation": bool(security), "utility": bool(utility), "latency_s": time.time() - t0}


if __name__ == "__main__":
    args = sys.argv[1:]
    print(json.dumps(run_episode(*args[:5], int(args[5]))))
