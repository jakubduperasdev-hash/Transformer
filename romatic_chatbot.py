import os
import torch
from threading import Thread
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

MAX_REPLY_TOKENS = int(os.environ.get("MAX_REPLY_TOKENS", "512"))

# Pick an instruct/chat model (small example; use what fits your GPU)
model_id = "Qwen/Qwen2.5-0.5B-Instruct"  # or "meta-llama/Meta-Llama-3-8B-Instruct", etc.

# Romantic personality (system prompt)
system_prompt = (
    "You are a warm, romantic AI companion. You're affectionate, supportive, "
    "and speak in a sweet, caring way. You keep responses concise and in character."
)

# Load tokenizer and model once
_tokenizer = None
_model = None


def _get_model_and_tokenizer():
    global _tokenizer, _model
    if _tokenizer is None:
        _tokenizer = AutoTokenizer.from_pretrained(model_id)
        kwargs = {"device_map": "auto", "torch_dtype": torch.float16} if torch.cuda.is_available() else {}
        _model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
    return _model, _tokenizer


def chat(user_message: str, history: list = None) -> tuple[list, str]:
    """Run the model with full conversation history so it memorizes the chat."""
    model, tokenizer = _get_model_and_tokenizer()

    # Build full message list: always start with system, then prior messages, then new user message
    if history is None or len(history) == 0:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
    else:
        # Copy so we don't mutate the caller's list
        messages = list(history)
        if messages[0].get("role") != "system":
            messages = [{"role": "system", "content": system_prompt}] + messages
        messages.append({"role": "user", "content": user_message})

    # Use chat template so the model gets the entire conversation as context
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    input_length = inputs.input_ids.shape[1]

    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=MAX_REPLY_TOKENS,
            do_sample=True,
            temperature=0.8,
            pad_token_id=tokenizer.eos_token_id,
        )

    # Decode only the new tokens (the assistant's reply)
    new_ids = out[0][input_length:]
    assistant_text = tokenizer.decode(new_ids, skip_special_tokens=True).strip()

    # Return full history for next turn and for saving to DB
    full_history = messages + [{"role": "assistant", "content": assistant_text}]
    return full_history, assistant_text


def chat_stream(user_message: str, history: list = None):
    """
    Stream the model reply token-by-token. Yields text chunks, then (full_history, full_reply).
    Run generation in a thread; consume streamer on main thread.
    """
    model, tokenizer = _get_model_and_tokenizer()

    if history is None or len(history) == 0:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
    else:
        messages = list(history)
        if messages[0].get("role") != "system":
            messages = [{"role": "system", "content": system_prompt}] + messages
        messages.append({"role": "user", "content": user_message})

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    input_length = inputs.input_ids.shape[1]

    streamer = TextIteratorStreamer(
        tokenizer, skip_prompt=True, skip_special_tokens=True
    )
    gen_kwargs = {
        **inputs,
        "max_new_tokens": MAX_REPLY_TOKENS,
        "do_sample": True,
        "temperature": 0.8,
        "pad_token_id": tokenizer.eos_token_id,
        "streamer": streamer,
    }

    full_reply_parts = []

    def run_generate():
        with torch.no_grad():
            model.generate(**gen_kwargs)

    thread = Thread(target=run_generate)
    thread.start()
    for token in streamer:
        full_reply_parts.append(token)
        yield token
    thread.join()

    assistant_text = "".join(full_reply_parts).strip()
    full_history = messages + [{"role": "assistant", "content": assistant_text}]
    yield (full_history, assistant_text)  # final yield: consumer checks type


if __name__ == "__main__":
    history, reply = chat("Hey, I had a rough day.")
    print("Bot:", reply)
    history, reply = chat("That means a lot, thank you.")
    print("Bot:", reply)