import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

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
            max_new_tokens=256,
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

if __name__ == "__main__":
    history, reply = chat("Hey, I had a rough day.")
    print("Bot:", reply)
    history, reply = chat("That means a lot, thank you.")
    print("Bot:", reply)