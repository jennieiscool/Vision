"""Local Kokoro voice blend and Faster Whisper transcription; no cloud audio."""
import io
import re
import shutil
import subprocess
import threading
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path


def spoken_text(text):
    """Keep conversational words and pauses, without speaking markup or emoji names."""
    text = re.sub(r'```[\s\S]*?(?:```|$)', ' Code is available in the chat. ', text)
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Remove keycap emoji as a unit so their underlying digit is not spoken.
    text = re.sub(r'[0-9#*]\ufe0f?\u20e3', ' ', text)
    text = ''.join(' ' if unicodedata.category(c)[0] == 'S' else c for c in text)
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[/\\]+', ' or ', text)
    text = text.translate(str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"', '—': ',', '–': ',', '…': '...'}))
    cleaned = []
    for character in text:
        category = unicodedata.category(character)
        if character.isspace() or category[0] in {'L', 'N'}:
            cleaned.append(character)
        elif category[0] == 'M' and character not in {'\ufe0e', '\ufe0f', '\u20e3'}:
            cleaned.append(character)
        elif character in ".,!?;:'":
            cleaned.append(character)
        else:
            cleaned.append(' ')
    text = re.sub(r'\s+', ' ', ''.join(cleaned)).strip()
    return text[:6000] if any(unicodedata.category(c)[0] in {'L', 'N'} for c in text) else ''


class Voice:
    def __init__(self, root: Path):
        self.root = root
        self.tts = None
        self.stt = None
        self.lock = threading.Lock()

    def speak(self, text, with_timing=False):
        import numpy as np
        import soundfile as sf
        from kokoro_onnx import Kokoro

        text = spoken_text(text)
        if not text:
            return {'audio': b'', 'words': [], 'duration': 0, 'silent': True} if with_timing else b''
        with self.lock:
            if self.tts is None:
                self.tts = Kokoro(str(self.root / "runtime/kokoro-v1.0.onnx"), str(self.root / "runtime/voices-v1.0.bin"))
            blend = self.tts.voices["bm_george"] * .65 + self.tts.voices["bm_fable"] * .35
            samples, rate = self.tts.create(text, voice=blend, speed=.93, lang="en-gb")
        buffer = io.BytesIO()
        sf.write(buffer, np.asarray(samples), rate, format="WAV", subtype="PCM_16")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return self.with_captions(buffer.getvalue(), text) if with_timing else buffer.getvalue()
        # About -0.35 semitones, with duration compensated to retain 0.93x pace.
        filters = "asetrate=23520,aresample=24000,atempo=1.020408,bass=g=1.5:f=110,equalizer=f=260:t=q:w=0.8:g=0.8,equalizer=f=2800:t=q:w=1:g=0.6,acompressor=threshold=0.16:ratio=1.35:attack=18:release=200:makeup=1.05,aecho=0.8:0.85:23:0.035,alimiter=limit=0.95"
        result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-af", filters, "-f", "wav", "pipe:1"], input=buffer.getvalue(), capture_output=True, timeout=180, creationflags=0x08000000)
        if result.returncode:
            raise RuntimeError("Voice post-processing failed")
        # FFmpeg's pipe WAV has unknown-length RIFF fields. Re-encode it with
        # finite sizes so Chromium's Web Audio decoder can reliably play it.
        processed, processed_rate = sf.read(io.BytesIO(result.stdout), dtype="float32")
        final = io.BytesIO()
        sf.write(final, processed, processed_rate, format="WAV", subtype="PCM_16")
        return self.with_captions(final.getvalue(), text) if with_timing else final.getvalue()

    def with_captions(self, audio, text):
        """Align the actual post-processed waveform, preserving the exact spoken source words.

        The installed Kokoro export exposes audio only, so Whisper supplies acoustic
        word boundaries. Grouped substitutions (numbers/contractions) share their
        measured spoken interval instead of drifting on a fixed reading timer.
        """
        from faster_whisper import WhisperModel
        import soundfile as sf
        import logging
        try:
            with self.lock:
                if self.stt is None:
                    self.stt = WhisperModel('base', device='cpu', compute_type='int8', download_root=str(self.root / 'runtime/whisper'))
                segments, _ = self.stt.transcribe(io.BytesIO(audio), language='en', word_timestamps=True,
                                                 vad_filter=False, beam_size=1, temperature=0,
                                                 condition_on_previous_text=False, initial_prompt=text[:1200])
                recognized = [word for segment in segments for word in segment.words or [] if word.word.strip()]
            source = text.split()
            normalize = lambda word: re.sub(r'[^\w]', '', word.casefold())
            matcher = SequenceMatcher(None, [normalize(word) for word in source], [normalize(word.word) for word in recognized], autojunk=False)
            duration = sf.info(io.BytesIO(audio)).duration
            aligned = []
            for tag, first, last, begin, end in matcher.get_opcodes():
                if tag == 'insert':
                    continue
                if tag == 'equal':
                    aligned.extend({'word': source[i], 'start': float(recognized[j].start), 'end': float(recognized[j].end)} for i, j in zip(range(first, last), range(begin, end)))
                    continue
                start = float(recognized[begin].start) if begin < len(recognized) else float(recognized[-1].end) if recognized else 0
                finish = float(recognized[end - 1].end) if end > begin else start
                if tag == 'delete':
                    start = float(recognized[begin - 1].end) if begin else 0
                    finish = float(recognized[begin].start) if begin < len(recognized) else duration
                weights = [max(1, len(normalize(word))) for word in source[first:last]]
                total = sum(weights) or 1
                for word, weight in zip(source[first:last], weights):
                    stop = start + max(0, finish - start) * weight / total
                    aligned.append({'word': word, 'start': start, 'end': stop})
                    total -= weight
                    start = stop
            # No acoustic evidence: play speech without invented captions.
            if not recognized:
                aligned = []
            return {'audio': audio, 'words': aligned, 'duration': duration}
        except Exception:
            logging.getLogger(__name__).exception('Word caption alignment unavailable')
            return {'audio': audio, 'words': [], 'duration': 0}

    def transcribe(self, path):
        from faster_whisper import WhisperModel
        with self.lock:
            if self.stt is None:
                self.stt = WhisperModel("base", device="cpu", compute_type="int8", download_root=str(self.root / "runtime/whisper"))
            segments, _ = self.stt.transcribe(str(path), language="en", vad_filter=False, beam_size=3,
                                              temperature=0, condition_on_previous_text=False)
            return " ".join(segment.text.strip() for segment in segments).strip()
