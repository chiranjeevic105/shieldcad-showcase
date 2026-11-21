"""Optional local LLM (any OpenAI-compatible server, e.g. vLLM) for parts with no template. Untested against a live model here."""
import json, os, re, urllib.request

SYSTEM = ("You write CadQuery Python for one mechanical part. Units mm. Only `import cadquery as cq` and `import math`. "
          "Assign the final cq.Workplane to a variable named result. No file I/O. Reply with ONE ```python block only.")


class LLM:
    def __init__(self, url, model, key=""):
        self.url, self.model, self.key = url.rstrip("/"), model, key

    @classmethod
    def from_env(cls):
        u = os.environ.get("SHIELDCAD_LLM_URL")
        return cls(u, os.environ.get("SHIELDCAD_LLM_MODEL", "local"), os.environ.get("SHIELDCAD_LLM_KEY", "")) if u else None

    def generate(self, prompt, feedback=None):
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
        if feedback:
            msgs.append({"role": "user", "content": "Previous attempt failed validation:\n" + feedback + "\nFix it."})
        req = urllib.request.Request(self.url + "/v1/chat/completions",
                                     json.dumps({"model": self.model, "messages": msgs, "temperature": 0.1}).encode(),
                                     {"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        text = json.load(urllib.request.urlopen(req, timeout=120))["choices"][0]["message"]["content"]
        m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
        return m.group(1) if m else text
