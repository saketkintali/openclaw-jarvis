#!/usr/bin/env python3
"""Audio transcription using faster-whisper (free, local)"""

import sys
import os

def transcribe(audio_path, model_size="tiny"):
    """Transcribe an audio file and return the text."""
    from faster_whisper import WhisperModel
    
    # Use int8 for CPU efficiency
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    
    segments, info = model.transcribe(audio_path, language="en")
    
    print(f"Transcribing: {audio_path}")
    print(f"Model: {model_size}, Language: {info.language}", file=sys.stderr)
    
    text = []
    for segment in segments:
        text.append(segment.text.strip())
    
    return " ".join(text)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transcribe.py <audio_file> [model_size]")
        sys.exit(1)
    
    audio_path = sys.argv[1]
    model_size = sys.argv[2] if len(sys.argv) > 2 else "tiny"
    
    if not os.path.exists(audio_path):
        print(f"Error: File not found: {audio_path}")
        sys.exit(1)
    
    result = transcribe(audio_path, model_size)
    print(result)
