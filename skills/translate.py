"""Vagar translation layer: 200-language understanding via NLLB-200.

Voice tools:
  detect_language - identify the language of text (fasttext lid.176, 176 langs)
  translate_text   - translate text between languages (NLLB-200 distilled 600M)

Design: lazy loading + idle unload. The fasttext model (~50MB) stays resident.
The NLLB model (~1GB) loads on first translation and unloads after 10 min idle
so it never fights Ollama for RAM.

Tokenization uses the transformers NLLB tokenizer with src_lang set, per the
model's documented usage. Raw sentencepiece does NOT handle the language
codes correctly -- do not "simplify" this back to raw SPM.

Dead languages (Latin, Ancient Greek, Sanskrit, etc.) skip NLLB entirely --
route those straight to the LLM, which reads them natively from training.
Undeciphered scripts (Linear A, Indus, Rongorongo) are NEVER translated;
Vagar says so plainly.
"""

try:
    from livekit.agents.llm import function_tool
except ImportError:  # pragma: no cover - allows testing off-laptop
    def function_tool(*_a, **_k):
        def _deco(f):
            return f
        return _deco

import os
import threading
import time

_BASE = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.normpath(os.path.join(
    _BASE, "..", "models", "translate"))
_LID_PATH = os.path.join(_MODEL_DIR, "lid.176.ftz")
# int8 conversion (mijuanlo, 594MB). Tokenization MUST use the transformers
# NLLB tokenizer with src_lang set -- raw sentencepiece mishandles lang codes.
_NLLB_DIR = os.path.join(_MODEL_DIR, "nllb-ct2-int8")

_NLLB_IDLE_SECS = 600  # unload NLLB after 10 min without use

_lid_model = None
_lid_lock = threading.Lock()
_nllb_translator = None
_nllb_tokenizers = {}  # src_lang -> tokenizer (cached)
_nllb_lock = threading.Lock()
_nllb_last_used = 0.0

# fasttext ISO 639 -> NLLB-200 Flores code. Covers the languages Vagar is
# most likely to hear. Anything unmapped falls back to a graceful message.
_ISO_TO_NLLB = {
    "en": "eng_Latn", "es": "spa_Latn", "fr": "fra_Latn",
    "de": "deu_Latn", "it": "ita_Latn", "pt": "por_Latn",
    "ru": "rus_Cyrl", "zh": "zho_Hans", "ja": "jpn_Jpan",
    "hi": "hin_Deva", "ar": "ara_Arab", "nl": "nld_Latn",
    "pl": "pol_Latn", "tr": "tur_Latn", "ko": "kor_Hang",
    "sv": "swe_Latn", "da": "dan_Latn", "no": "nob_Latn",
    "fi": "fin_Latn", "el": "ell_Grek", "he": "heb_Hebr",
    "hu": "hun_Latn", "cs": "ces_Latn", "ro": "ron_Latn",
    "uk": "ukr_Cyrl", "vi": "vie_Latn", "th": "tha_Thai",
    "id": "ind_Latn", "ms": "zsm_Latn", "tl": "tgl_Latn",
    "bn": "ben_Beng", "ta": "tam_Taml", "te": "tel_Telu",
    "mr": "mar_Deva", "gu": "guj_Gujr", "pa": "pan_Guru",
    "ur": "urd_Arab", "fa": "pes_Arab", "sw": "swh_Latn",
    "am": "amh_Ethi", "yo": "yor_Latn", "ha": "hau_Latn",
    "ig": "ibo_Latn", "zu": "zul_Latn", "af": "afr_Latn",
    "qu": "quy_Latn", "ht": "hat_Latn", "ca": "cat_Latn",
}

# Dead languages with real corpora: the LLM reads these natively.
# Never send them through NLLB.
_DEAD_LANGS = {
    "la": "Latin", "grc": "Ancient Greek", "sa": "Sanskrit",
    "lzh": "Classical Chinese", "he": "Biblical Hebrew",
    "ang": "Old English", "cop": "Coptic", "gez": "Ge'ez",
    "akk": "Akkadian",
}
_THIN_DEAD = {"cop", "gez", "akk"}  # answer, but flag uncertainty

# Undeciphered: nobody on earth can read these. Never pretend.
_UNDECIPHERED = {"linear_a", "indus", "rongorongo", "proto_elamite",
                 "phaistos", "quipu"}


def _get_lid():
    global _lid_model
    with _lid_lock:
        if _lid_model is None:
            import fasttext
            if not os.path.exists(_LID_PATH):
                raise RuntimeError("lid.176.ftz not found at " + _LID_PATH)
            _lid_model = fasttext.load_model(_LID_PATH)
        return _lid_model


def _get_nllb(src_code):
    """Load NLLB translator + tokenizer for src_code (cached). Updates idle timer."""
    global _nllb_translator, _nllb_last_used
    with _nllb_lock:
        if _nllb_translator is None:
            import ctranslate2
            if not os.path.isdir(_NLLB_DIR):
                raise RuntimeError("NLLB model not found at " + _NLLB_DIR)
            _nllb_translator = ctranslate2.Translator(_NLLB_DIR, device="cpu")
        if src_code not in _nllb_tokenizers:
            import transformers
            _nllb_tokenizers[src_code] = transformers.AutoTokenizer.from_pretrained(
                _NLLB_DIR, src_lang=src_code)
        _nllb_last_used = time.time()
        return _nllb_translator, _nllb_tokenizers[src_code]


def _maybe_unload_nllb():
    """Free the NLLB model if idle past the timeout. Safe to call anytime."""
    global _nllb_translator, _nllb_tokenizers
    with _nllb_lock:
        if (_nllb_translator is not None
                and time.time() - _nllb_last_used > _NLLB_IDLE_SECS):
            _nllb_translator = None
            _nllb_tokenizers = {}
            return True
    return False


def _nllb_code(iso):
    return _ISO_TO_NLLB.get((iso or "").lower().strip())


@function_tool
async def detect_language(text: str) -> str:
    """Identify the language of a piece of text. Returns the ISO 639 code
    (e.g. 'es' for Spanish, 'fr' for French) and the language name."""
    text = (text or "").strip()
    if not text:
        return "no text given"
    try:
        model = _get_lid()
    except Exception as e:
        return f"language detection unavailable: {e}"
    # fasttext needs a minimum length; pad very short inputs
    probe = text if len(text) >= 10 else (text + " ") * 4
    labels, probs = model.predict(probe.strip(), k=1)
    iso = labels[0].replace("__label__", "")
    conf = float(probs[0])
    return f"{iso} (confidence {conf:.2f})"


@function_tool
async def translate_text(text: str, target_lang: str,
                         source_lang: str = "auto") -> str:
    """Translate text to a target language. target_lang is an ISO 639 code
    like 'es', 'fr', 'de', 'zh'. Use source_lang='auto' to detect first,
    or pass the ISO code you already know. Dead languages (Latin, Ancient
    Greek, Sanskrit...) are NOT translated here -- ask the brain directly."""
    text = (text or "").strip()
    if not text:
        return "no text given"
    tgt_iso = (target_lang or "").lower().strip()
    if tgt_iso in _DEAD_LANGS:
        return (f"{_DEAD_LANGS[tgt_iso]} is a classical language -- "
                "I read it directly, no translation needed. Ask me about it.")
    if any(u in text.lower() for u in _UNDECIPHERED):
        return ("That's an undeciphered script -- nobody on earth can read it, "
                "and I won't pretend to. I can tell you what scholars know "
                "about the script itself.")

    src_iso = (source_lang or "auto").lower().strip()
    if src_iso == "auto":
        det = await detect_language(text)
        src_iso = det.split()[0]
    if src_iso in _DEAD_LANGS:
        return (f"Detected {_DEAD_LANGS[src_iso]} -- I read it directly, "
                "no translation needed. Ask me about it.")

    src_code = _nllb_code(src_iso)
    tgt_code = _nllb_code(tgt_iso)
    if not src_code:
        return f"I can't identify '{src_iso}' as a translatable language."
    if not tgt_code:
        return f"I don't have a translation target for '{tgt_iso}'."
    if src_code == tgt_code:
        return text  # already in the target language

    try:
        translator, tokenizer = _get_nllb(src_code)
    except Exception as e:
        return f"translation engine unavailable: {e}"

    def _run():
        # Documented NLLB+CT2 pattern: transformers tokenizer with src_lang,
        # convert to tokens, translate with target prefix, skip first output
        # token (echoed target lang), decode back through the tokenizer.
        source = tokenizer.convert_ids_to_tokens(tokenizer.encode(text))
        results = translator.translate_batch(
            [source], target_prefix=[[tgt_code]],
            beam_size=4, max_decoding_length=256)
        target = results[0].hypotheses[0][1:]
        return tokenizer.decode(tokenizer.convert_tokens_to_ids(target))

    import asyncio
    try:
        out = await asyncio.to_thread(_run)
    except Exception as e:
        return f"translation failed: {e}"
    return out.strip()
