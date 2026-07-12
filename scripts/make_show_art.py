import base64, json, os, sys, urllib.request

KEY = os.environ["OPENROUTER_IMAGE_KEY"]  # never committed; pass via env
MODELS = ["google/gemini-3-pro-image-preview", "google/gemini-2.5-flash-image"]

STYLE = ("Square 1:1 podcast cover art. Flat vintage screen-print poster "
         "style with heavy film grain, high contrast, limited palette: "
         "near-black indigo background (#0b0b12), warm amber (#ffb454), "
         "signal red (#ff4757), a touch of teal (#4ecdc4). Bold condensed "
         "uppercase title typography, cleanly legible. No real people, no "
         "real logos or brands. Professional, iconic, Apple-Podcasts-ready.")

JOBS = {
    "center-ice": (
        "A lone vintage broadcast microphone standing at center ice of an "
        "empty small-town hockey barn at night, dramatic cone of amber "
        "arena light, faint breath of cold in the air, red center line "
        "underfoot. Title text: 'CENTER ICE'. Small subtitle text: 'ON THE "
        "FREQUENCY 108.1'."),
    "dream-court": (
        "A rotary telephone resting on a judge's wooden bench that floats "
        "in a starry indigo night sky beside a crescent moon, a warm desk "
        "lamp glowing amber, thin dreamlike mist. Title text: 'DREAM "
        "COURT'. Small subtitle text: 'THE FREQUENCY, LATE NIGHTS'."),
    "static-hour": (
        "A conspiracy corkboard lit by one desk lamp: red string connecting "
        "polaroid photos of a toaster, a crosswalk button, and a goose "
        "silhouette, with a vintage shortwave radio dial glowing amber "
        "below, eerie teal glow at the edges. Title text: 'THE STATIC "
        "HOUR'. Small subtitle text: 'ONE THEORY AT A TIME'."),
}

def gen(model, prompt):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    imgs = d["choices"][0]["message"].get("images") or []
    if not imgs:
        raise RuntimeError(f"no image in response: {str(d)[:300]}")
    url = imgs[0]["image_url"]["url"]
    b64 = url.split(",", 1)[1]
    return base64.b64decode(b64)

for key, scene in JOBS.items():
    prompt = STYLE + "\n\nScene: " + scene
    for model in MODELS:
        try:
            png = gen(model, prompt)
            out = f"{key}-raw.png"
            open(out, "wb").write(png)
            print(f"{key}: {model} -> {len(png)//1024}KB")
            break
        except Exception as e:
            print(f"{key}: {model} failed: {str(e)[:160]}")
    else:
        sys.exit(1)
