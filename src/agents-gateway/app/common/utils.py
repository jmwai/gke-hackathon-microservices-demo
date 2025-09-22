import os
import vertexai

from vertexai import agent_engines


def fetch_google_api_key():
    """Fetches the Google API key from Secret Manager and sets it as an env var."""
    secret_name = os.environ.get("GOOGLE_API_KEY_SECRET_NAME")
    project_id = os.environ.get("PROJECT_ID")
    if secret_name and project_id:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            version_name = client.secret_version_path(
                project_id, secret_name, "latest")
            response = client.access_secret_version(name=version_name)
            api_key = response.payload.data.decode("UTF-8")
            os.environ["GOOGLE_API_KEY"] = api_key
            print("Successfully fetched and set GOOGLE_API_KEY from Secret Manager.")
        except Exception as e:
            print(
                f"ERROR: Failed to fetch Google API key from Secret Manager: {e}")


def get_or_create_agent_engine(display_name: str) -> agent_engines.AgentEngine:
    """Gets or creates a Vertex AI Agent Engine."""
    existing_engines = agent_engines.AgentEngine.list(
        filter=f'display_name="{display_name}"'
    )
    if existing_engines:
        print(
            f"Found existing Agent Engine: {existing_engines[0].resource_name}")
        return existing_engines[0]
    else:
        new_engine = agent_engines.create(display_name=display_name)
        print(f"Created new Agent Engine: {new_engine.resource_name}")
        return new_engine
