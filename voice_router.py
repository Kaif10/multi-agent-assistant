#!/usr/bin/env python3
"""
Voice router: push-to-talk to your agent.

- Press Enter to start recording. It records until silence (or max seconds),
  transcribes with OpenAI ASR, routes text to agent_router.handle(), and
  (optionally) speaks the reply via OpenAI TTS.

Env:
  OPENAI_API_KEY     - required
  ASR_MODEL          - default: whisper-1
  TTS_MODEL          - default: gpt-4o-mini-tts
  USE_TTS            - 1/true to enable TTS (default: 1)
  PTT_MAX_SECONDS    - max seconds per utterance (default: 30)
  DEFAULT_ACCOUNT_EMAIL - used by agent_router if not passed some other way
"""
import os, sys, time, queue, tempfile, threading, subprocess, io
import numpy as np
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv

load_dotenv()

# Try to import the router directly for speed; fallback to subprocess if import fails
try:
    import agent_router as router
    _HAS_DIRECT_ROUTER = True
except Exception:
    router = None
    _HAS_DIRECT_ROUTER = False

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

ASR_MODEL = os.getenv("ASR_MODEL", "whisper-1")
TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
USE_TTS  = os.getenv("USE_TTS", "1").lower() in {"1","true","yes","on"}
PTT_MAX_SECONDS = int(os.getenv("PTT_MAX_SECONDS", "30"))
SAMPLE_RATE = 16000
CHANNELS = 1

# --- Audio utils ------------------------------------------------------------
def _rms(block: np.ndarray) -> float:
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(block))))

def record_until_silence(samplerate=SAMPLE_RATE, threshold=0.015, min_voice_sec=0.6, silence_hold=1.0, max_seconds=PTT_MAX_SECONDS):
    """Record mono audio until we detect 'silence' for silence_hold seconds after having voice.
    Returns path to a temp WAV file (16kHz PCM16).
    """
    q: "queue.Queue[np.ndarray]" = queue.Queue()
    stop_flag = threading.Event()

    def cb(indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        q.put(indata.copy())

    BLOCKSIZE = 1024
    wav_path = None
    voiced_any = False
    last_voice_time = None
    start_time = time.time()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        wav_path = f.name

    with sd.InputStream(channels=CHANNELS, samplerate=samplerate, blocksize=BLOCKSIZE, dtype="float32", callback=cb):
        with sf.SoundFile(wav_path, mode="w", samplerate=samplerate, channels=CHANNELS, subtype="PCM_16") as out:
            while True:
                if time.time() - start_time >= max_seconds:
                    break
                try:
                    block = q.get(timeout=0.5)
                except queue.Empty:
                    if voiced_any and last_voice_time and (time.time() - last_voice_time >= silence_hold):
                        break
                    continue

                rms = _rms(block)
                out.write(block)
                now = time.time()
                if rms >= threshold:
                    if not voiced_any and (now - start_time) >= min_voice_sec:
                        voiced_any = True
                    last_voice_time = now
                if voiced_any and last_voice_time and (now - last_voice_time >= silence_hold):
                    break

    return wav_path

# --- OpenAI helpers ----------------------------------------------------------
def transcribe(wav_path: str) -> str:
    if OpenAI is None:
        return "(ASR error: openai package not available)"
    client = OpenAI()
    try:
        with open(wav_path, "rb") as f:
            resp = client.audio.transcriptions.create(model=ASR_MODEL, file=f)
        text = getattr(resp, "text", None) or (resp.get("text") if isinstance(resp, dict) else None)
        return text or ""
    except Exception as e:
        return f"(ASR error: {e})"

def tts_play(text: str):
    if not USE_TTS or not text:
        return
    if OpenAI is None:
        print("(TTS disabled: openai package not available)")
        return
    client = OpenAI()
    try:
        speech = client.audio.speech.create(model=TTS_MODEL, voice="alloy", input=text)
        audio_bytes = getattr(speech, "content", None)
        if audio_bytes is None and hasattr(speech, "read"):
            audio_bytes = speech.read()
        if audio_bytes is None and isinstance(speech, dict):
            audio_bytes = speech.get("audio") or speech.get("content")
        if not audio_bytes:
            print("(TTS returned no audio)")
            return
        data, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
        sd.play(data, sr); sd.wait()
    except Exception as e:
        print(f"(TTS error: {e})")

# --- Router call -------------------------------------------------------------
def run_once(prompt_text: str):
    prompt_text = (prompt_text or "").strip()
    if not prompt_text:
        print("(empty prompt)")
        return
    try:
        if _HAS_DIRECT_ROUTER and hasattr(router, "handle"):
            account = os.getenv("DEFAULT_ACCOUNT_EMAIL")
            reply = router.handle(prompt_text, account_email=account)
            print(f"Agent:\n{reply}")
            tts_play(reply)
        else:
            cmd = [sys.executable, "-u", "agent_router.py", prompt_text]
            print(f"[exec] {' '.join(cmd)}")
            out = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if out.stdout:
                print(out.stdout.strip())
                tts_play(out.stdout.strip())
            if out.stderr:
                print(out.stderr.strip(), file=sys.stderr)
    except Exception as e:
        print(f"(router error: {e})")

def main():
    print("Voice router ready. Press Enter, speak your request, then pause. Ctrl+C to quit.")
    try:
        while True:
            input("")
            print("Listening… (speak now)")
            wav = record_until_silence()
            print("Processing…")
            text = transcribe(wav)
            if not text or text.startswith("(ASR error"):
                print(text or "(heard nothing)")
                tts_play("I didn’t catch that. Please try again.")
                continue
            print(f"You: {text}")
            run_once(text)
            print("\nPress Enter for the next request…")
    except KeyboardInterrupt:
        print("\nbye!")

if __name__ == "__main__":
    main()
