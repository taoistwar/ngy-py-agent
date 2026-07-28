import os
import ollama


def _normalize_ollama_host() -> str:
    import dotenv

    dotenv.load_dotenv()
    host = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
    if not host:
        host = "http://127.0.0.1:11434"
    if "://" not in host:
        host = f"http://{host}"
    return host


def ollama_models():
    host = _normalize_ollama_host()
    print("ollama host:", host)
    client = ollama.Client(host=host)
    try:
        response = client.list()
    except Exception as exc:
        print(f"Failed to connect to Ollama at {host}: {exc}")
        return

    models = response.get("models", [])

    for model in models:
        print("=" * 20)
        print(model)
        print("-" * 10)
        print("model", model.get("model"))
        print("modified_at:", model.get("modified_at"))
        print("digest:", model.get("digest"))
        print("size:", model.get("size"))
        print("details:", model.get("details"))


if __name__ == "__main__":
    ollama_models()
