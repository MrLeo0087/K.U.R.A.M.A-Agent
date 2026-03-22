import asyncio
import aiohttp
from pathlib import Path

BASE_URL = "https://image-api.satorugojo0087.workers.dev/"

async def fetch_image(session, prompt, index):
    """Fetch a single image for a given prompt."""
    try:
        async with session.get(BASE_URL, params={"prompt": prompt}) as response:
            if response.status == 200:
                image_bytes = await response.read()
                filename = rf"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_2\Image\image_{index}_{prompt[:20].replace(' ', '_')}.jpg"
                Path(filename).write_bytes(image_bytes)
                print(f"✅ [{index}] Saved: {filename}")
                return {"index": index, "prompt": prompt, "file": filename, "success": True}
            else:
                text = await response.text()
                print(f"❌ [{index}] Failed: {text}")
                return {"index": index, "prompt": prompt, "error": text, "success": False}

    except Exception as e:
        print(f"❌ [{index}] Exception: {str(e)}")
        return {"index": index, "prompt": prompt, "error": str(e), "success": False}


async def generate_images(prompts: list[str]):
    """Generate multiple images concurrently."""
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_image(session, prompt, i)
            for i, prompt in enumerate(prompts)
        ]
        results = await asyncio.gather(*tasks)
    return results


def run(prompts: list[str]):
    """Main entry point — call this from your code."""
    return asyncio.run(generate_images(prompts))


# ---- Example usage ----
if __name__ == "__main__":
    prompts = [
        "a cat sitting on the moon",
        "a futuristic city at sunset",
        "a dragon flying over mountains",
        "a cozy cabin in the snow",
        "an astronaut riding a horse",
    ]

    results = run(prompts)

    print("\n--- Summary ---")
    for r in results:
        if r["success"]:
            print(f"✅ Prompt: '{r['prompt']}' → {r['file']}")
        else:
            print(f"❌ Prompt: '{r['prompt']}' → Error: {r['error']}")