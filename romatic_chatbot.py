import torch
from transformers import pipeline

# Pick an instruct/chat model (small example; use what fits your GPU)
model_id = "Qwen/Qwen2.5-0.5B-Instruct"  # or "meta-llama/Meta-Llama-3-8B-Instruct", etc.

# Use float16 on GPU (bfloat16 not supported on all hardware); float32 on CPU
if torch.cuda.is_available():
    pipe = pipeline(
        task="text-generation",
        model=model_id,
        torch_dtype=torch.float16,
        device_map="auto",
    )
else:
    pipe = pipeline(task="text-generation", model=model_id)

# Romantic personality (system prompt)
system_prompt = (
    "You are a warm, romantic AI companion. You're affectionate, supportive, "
    "and speak in a sweet, caring way. You keep responses concise and in character."
)

def chat(user_message: str, history: list = None) -> tuple[list, str]:
    if history is None:
        history = [{"role": "system", "content": system_prompt}]
    history.append({"role": "user", "content": user_message})

    out = pipe(history, max_new_tokens=256, do_sample=True, temperature=0.8)
    messages = out[0]["generated_text"]
    assistant_msg = messages[-1]["content"]
    history = messages  # keep full conversation for context
    return history, assistant_msg

if __name__ == "__main__":
    history, reply = chat("Hey, I had a rough day.")
    print("Bot:", reply)
    history, reply = chat("That means a lot, thank you.")
    print("Bot:", reply)