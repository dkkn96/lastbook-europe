"""The GGUF files supported by the bundled Gemma prompt and tool parser."""

import json
from pathlib import Path


MODELS = (
    {'id': 'gemma-4-26b-a4b', 'title': 'Gemma 4 26B A4B', 'file': 'gemma-4-26B-A4B-it-UD-Q4_K_M.gguf',
     'size': 16_947_541_728, 'sha256': 'f2c28b3dc4776931ac6f879e11f203dec637ea0f14267a86ec8f6165f63f293f',
     'repo': 'unsloth/gemma-4-26B-A4B-it-GGUF', 'revision': 'c099eb48e663fd284577b04978a94ffccb261841',
     'memory_bytes': 18_160_150_464 + 867_233_792},
    {'id': 'gemma-4-e4b', 'title': 'Gemma 4 E4B', 'file': 'gemma-4-E4B-it-Q4_K_M.gguf',
     'size': 4_977_171_584, 'sha256': '85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87',
     'repo': 'unsloth/gemma-4-E4B-it-GGUF', 'revision': 'bfc15c382204943c3a8fff0c750b94ae2364d7a3',
     'memory_bytes': 6_307_922_592},
)


def manifest_entry(model):
    entry = {k: v for k, v in model.items() if k not in ('repo', 'revision')}
    entry['url'] = f'https://huggingface.co/{model["repo"]}/resolve/{model["revision"]}/{model["file"]}?download=true'
    entry['available'] = True
    return entry


def read_state(library):
    try:
        data = json.loads((Path(library) / 'derived' / 'llm' / 'state.json').read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
