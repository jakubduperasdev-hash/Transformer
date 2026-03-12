"""
Quick benchmark: measure chatbot response time on this machine.
Run: python benchmark_chat.py
"""
import time
import sys

def main():
    print("Benchmarking chatbot response time (this may take a minute)...")
    sys.stdout.flush()

    from romatic_chatbot import chat
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}\n")

    # First call includes model load
    t0 = time.perf_counter()
    history, reply = chat("Hello! How are you?")
    first_time = time.perf_counter() - t0
    print(f"First response (includes model load): {first_time:.1f}s")
    print(f"  Reply length: {len(reply)} chars\n")

    # Subsequent calls (model already in memory)
    times = []
    for i, msg in enumerate(["What's your name?", "Tell me a short joke.", "Thanks!"]):
        t0 = time.perf_counter()
        history, reply = chat(msg, history=history)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        print(f"  Message {i+2}: {elapsed:.1f}s ({len(reply)} chars)")

    if times:
        avg = sum(times) / len(times)
        print(f"\n--- Summary ---")
        print(f"First response (cold): {first_time:.1f}s")
        print(f"Average response (warm): {avg:.1f}s")
        print(f"Min / Max (warm): {min(times):.1f}s / {max(times):.1f}s")

if __name__ == "__main__":
    main()
