import json, time, requests, os
from typing import Dict, Any, Optional, List

class ComfyClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def queue_prompt(self, workflow: Dict[str, Any], prompt_id: Optional[str]=None):
        body = {"prompt": workflow, "client_id": "yt_auto"}
        if prompt_id:
            body["prompt_id"] = prompt_id
        r = requests.post(f"{self.base}/prompt", json=body, timeout=60)
        r.raise_for_status()
        return r.json()

    def get_history(self, prompt_id: str):
        r = requests.get(f"{self.base}/history/{prompt_id}", timeout=60)
        r.raise_for_status()
        return r.json()

    def fetch_binary(self, filename: str, subfolder: str, save_to: str):
        params = {"filename": filename, "subfolder": subfolder, "type": "output"}
        import requests
        r = requests.get(f"{self.base}/view", params=params, timeout=300)
        r.raise_for_status()
        with open(save_to, "wb") as f:
            f.write(r.content)
    def fetch_image(self, filename: str, subfolder: str, save_to: str):
        return self.fetch_binary(filename, subfolder, save_to)
        # ComfyUI view endpoint: /view?filename=...&subfolder=...&type=output
        params = {"filename": filename, "subfolder": subfolder, "type": "output"}
        r = requests.get(f"{self.base}/view", params=params, timeout=120)
        r.raise_for_status()
        with open(save_to, "wb") as f:
            f.write(r.content)

    def wait_for_complete(self, prompt_id: str, poll=2.0, timeout=600):
        t0 = time.time()
        while True:
            h = self.get_history(prompt_id)
            if prompt_id in h and "outputs" in h[prompt_id]:
                return h[prompt_id]
            if time.time() - t0 > timeout:
                raise TimeoutError("ComfyUI generation timed out")
            time.sleep(poll)
