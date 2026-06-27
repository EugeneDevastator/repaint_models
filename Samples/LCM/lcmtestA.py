import sys
import os
import itertools
from diffusers import AutoPipelineForImage2Image, LCMScheduler
import torch
from PIL import Image

os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

prompt = sys.argv[1] if len(sys.argv) > 1 else "a cat"
input_image_path = sys.argv[2] if len(sys.argv) > 2 else "input.png"

RESOLUTION = 512

# --- All dims to permute ---
strength_list  = [0.2, 0.3, 0.5]
guidance_list  = [12, 24]
steps_list     = [24]
loopback_list  = [1, 2, 3]

os.makedirs("lcm_compare", exist_ok=True)

base_image = Image.open(input_image_path).convert("RGB").resize((RESOLUTION, RESOLUTION))

pipe = AutoPipelineForImage2Image.from_pretrained(
    "SimianLuo/LCM_Dreamshaper_v7",
    torch_dtype=torch.float32,
    local_files_only=True
)
pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
pipe = pipe.to("cpu")
pipe.safety_checker = None


def fname_for(strength, guidance, steps, loops):
    return f"lcm_compare/str{strength}_cfg{guidance}_steps{steps}_loops{loops}.png"


def find_last_loop(strength, guidance, steps):
    """Return (last_n, last_img) — highest cached loop for this combo."""
    last_n = 0
    last_img = None
    for n in sorted(loopback_list, reverse=True):
        f = fname_for(strength, guidance, steps, n)
        if os.path.exists(f):
            last_n = n
            last_img = Image.open(f).convert("RGB").resize((RESOLUTION, RESOLUTION))
            break
    return last_n, last_img


total = len(strength_list) * len(guidance_list) * len(steps_list)
combo_idx = 0

for strength, guidance, steps in itertools.product(strength_list, guidance_list, steps_list):
    combo_idx += 1
    print(f"\n[{combo_idx}/{total}] strength={strength} guidance={guidance} steps={steps}", flush=True)

    max_loops = max(loopback_list)

    # Check if all loops already done
    if all(os.path.exists(fname_for(strength, guidance, steps, n)) for n in loopback_list):
        print("  All loops cached, skipping.", flush=True)
        continue

    last_n, last_img = find_last_loop(strength, guidance, steps)
    current = last_img if last_img else base_image.copy()
    start_n = last_n + 1

    generator = torch.Generator().manual_seed(2242)

    for n in range(start_n, max_loops + 1):
        try:
            current = pipe(
                prompt, image=current,
                num_inference_steps=steps,
                strength=strength,
                guidance_scale=guidance,
                width=RESOLUTION, height=RESOLUTION,
                generator=generator,
            ).images[0]
        except Exception as e:
            print(f"  ERROR loop={n}: {e}", flush=True)
            current = Image.new("RGB", (RESOLUTION, RESOLUTION), (0, 0, 0))

        if n in loopback_list:
            f = fname_for(strength, guidance, steps, n)
            if not os.path.exists(f):
                current.save(f)
                print(f"  saved {f}", flush=True)
            else:
                print(f"  exists {f}", flush=True)

print("\nDone.", flush=True)
