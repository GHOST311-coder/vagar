"""Vagar speaker verification — local, private, no cloud.

ECAPA-TDNN (SpeechBrain, Apache 2.0, ~80MB) on CPU. 192-dim embeddings,
~20ms per embedding. Only embeddings are stored — never raw audio.

Usage:
    python speaker_id.py enroll <name> sample1.wav sample2.wav sample3.wav
    python speaker_id.py verify <name> test.wav
    python speaker_id.py list
"""
import os
import sys
import json
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE, "models", "spkrec-ecapa-voxceleb")
PROFILES_DIR = os.path.join(BASE, "speaker_profiles")
TARGET_SR = 16000

_classifier = None


def _load_classifier():
    global _classifier
    if _classifier is None:
        from speechbrain.inference import SpeakerRecognition
        os.makedirs(MODEL_DIR, exist_ok=True)
        _classifier = SpeakerRecognition.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=MODEL_DIR,
            run_opts={"device": "cpu"},
        )
    return _classifier


def _to_16k_mono(samples: np.ndarray, sr: int) -> np.ndarray:
    """Resample to 16kHz mono float32 in [-1, 1]."""
    import librosa
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != TARGET_SR:
        x = librosa.resample(x, orig_sr=sr, target_sr=TARGET_SR)
    m = np.max(np.abs(x))
    if m > 1.0:
        x = x / m
    return x.astype(np.float32)


def _read_audio(path: str):
    import soundfile as sf
    data, sr = sf.read(path, dtype="float32", always_2d=False)
    return _to_16k_mono(data, sr)


def embed_samples(samples: np.ndarray, sr: int) -> np.ndarray:
    """192-dim L2-normalized speaker embedding from raw PCM."""
    import torch
    clf = _load_classifier()
    wav = _to_16k_mono(samples, sr)
    if len(wav) < TARGET_SR:  # need at least ~1s
        raise ValueError("need at least 1 second of audio")
    with torch.no_grad():
        emb = clf.encode_batch(torch.from_numpy(wav).unsqueeze(0))
    v = emb.squeeze().cpu().numpy().astype(np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def embed_file(path: str) -> np.ndarray:
    return embed_samples(_read_audio(path), TARGET_SR)


def _profile_path(name: str) -> str:
    safe = "".join(c for c in name.lower() if c.isalnum() or c in "_-") or "user"
    return os.path.join(PROFILES_DIR, safe + ".npz")


def enroll(name: str, wav_paths: list) -> dict:
    """Build a voice profile from 2+ samples. Stores embedding only."""
    if len(wav_paths) < 2:
        raise ValueError("enroll needs at least 2 voice samples")
    embs = [embed_file(p) for p in wav_paths]
    embs = np.stack(embs)
    # genuine pairwise similarities for threshold calibration
    sims = []
    for i in range(len(embs)):
        for j in range(i + 1, len(embs)):
            sims.append(float(np.dot(embs[i], embs[j])))
    mean_emb = embs.mean(axis=0)
    mean_emb = mean_emb / np.linalg.norm(mean_emb)
    # threshold: just below the weakest genuine match, clamped sane
    thr = min(sims) - 0.10 if sims else 0.45
    thr = float(max(0.35, min(0.60, thr)))
    os.makedirs(PROFILES_DIR, exist_ok=True)
    np.savez(_profile_path(name),
             embedding=mean_emb.astype(np.float32),
             threshold=np.float32(thr),
             genuine_sims=np.array(sims, dtype=np.float32))
    return {"name": name, "threshold": round(thr, 3),
            "genuine_sims": [round(s, 3) for s in sims],
            "samples": len(wav_paths)}


def load_profile(name: str):
    p = _profile_path(name)
    if not os.path.isfile(p):
        return None
    d = np.load(p)
    return {"embedding": d["embedding"], "threshold": float(d["threshold"])}


def verify_samples(samples: np.ndarray, sr: int, name: str):
    """Returns (is_match: bool, similarity: float, threshold: float)."""
    prof = load_profile(name)
    if prof is None:
        return False, 0.0, 0.45
    emb = embed_samples(samples, sr)
    sim = float(np.dot(emb, prof["embedding"]))
    return sim >= prof["threshold"], sim, prof["threshold"]


def verify_file(path: str, name: str):
    data = _read_audio(path)
    return verify_samples(data, TARGET_SR, name)


def list_profiles():
    if not os.path.isdir(PROFILES_DIR):
        return []
    return [f[:-4] for f in os.listdir(PROFILES_DIR) if f.endswith(".npz")]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "enroll" and len(sys.argv) >= 5:
        print(json.dumps(enroll(sys.argv[2], sys.argv[3:]), indent=2))
    elif cmd == "verify" and len(sys.argv) == 4:
        ok, sim, thr = verify_file(sys.argv[3], sys.argv[2])
        print(json.dumps({"match": ok, "similarity": round(sim, 3),
                          "threshold": thr, "profile": sys.argv[2]}, indent=2))
    elif cmd == "list":
        print(json.dumps(list_profiles()))
    else:
        print(__doc__)


def enroll_from_pcm(name: str, clips: list) -> dict:
    """Build a voice profile from in-memory (samples, sr) clips.
    Stores embedding only — never raw audio."""
    if len(clips) < 2:
        raise ValueError("enroll needs at least 2 voice samples")
    embs = [embed_samples(np.asarray(s, dtype=np.float32), int(sr))
            for s, sr in clips]
    embs = np.stack(embs)
    sims = []
    for i in range(len(embs)):
        for j in range(i + 1, len(embs)):
            sims.append(float(np.dot(embs[i], embs[j])))
    mean_emb = embs.mean(axis=0)
    mean_emb = mean_emb / np.linalg.norm(mean_emb)
    thr = min(sims) - 0.10 if sims else 0.45
    thr = float(max(0.35, min(0.60, thr)))
    os.makedirs(PROFILES_DIR, exist_ok=True)
    np.savez(_profile_path(name),
             embedding=mean_emb.astype(np.float32),
             threshold=np.float32(thr),
             genuine_sims=np.array(sims, dtype=np.float32))
    return {"name": name, "threshold": round(thr, 3),
            "genuine_sims": [round(s, 3) for s in sims],
            "samples": len(clips)}
