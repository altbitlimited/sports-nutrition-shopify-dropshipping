import os
import subprocess
from pathlib import Path
from dotenv import dotenv_values

def push_fly_secrets(env_path=".env.production"):
    env_file = Path(env_path)

    if not env_file.exists():
        print(f"❌ {env_path} not found.")
        return

    # Parse .env.production into a dictionary
    secrets = dotenv_values(env_file)

    if not secrets:
        print(f"⚠️ No secrets found in {env_path}.")
        return

    print(f"🚀 Pushing {len(secrets)} secrets to Fly.io...")

    for key, value in secrets.items():
        if value is None:
            print(f"⚠️ Skipping {key} (empty value)")
            continue

        try:
            subprocess.run(
                ["fly", "secrets", "set", f"{key}={value}"],
                check=True
            )
            print(f"✅ {key} set")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to set {key}: {e}")

    print("🎉 Done!")

if __name__ == "__main__":
    push_fly_secrets()
