"""Pull a few clips from the MIMII dataset (CC BY-SA 4.0) without downloading the 7-11 GB zips.

zipfile only needs a seekable file, so HTTP range requests read the zip's index and then just the chosen WAVs.
Saves channel 0 as 16 kHz mono OGG in static/sounds/mimii. Run from src: ../.venv/bin/python tools/fetch_mimii.py
"""
import io
import sys
import zipfile
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

RECORD = "https://zenodo.org/api/records/3384388/files/{}/content"
MACHINES = ["fan", "pump", "slider", "valve"]
OUT = Path(__file__).resolve().parents[1] / "static" / "sounds" / "mimii"


class RangeFile(io.RawIOBase):
    def __init__(self, url):
        self.url, self.pos, self.client = url, 0, httpx.Client(follow_redirects=True, timeout=120)
        self.size = int(self.client.head(url).headers["content-length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence] + offset
        return self.pos

    def tell(self):
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        data = self.client.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}).content
        b[: len(data)] = data
        self.pos += len(data)
        return len(data)


def main(snr="6_dB"):
    OUT.mkdir(parents=True, exist_ok=True)
    for machine in MACHINES:
        z = zipfile.ZipFile(io.BufferedReader(RangeFile(RECORD.format(f"{snr}_{machine}.zip")), buffer_size=1 << 20))
        names = sorted(n for n in z.namelist() if n.endswith(".wav") and "/id_00/" in n)
        for condition in ("normal", "abnormal"):
            name = next(n for n in names if f"/{condition}/" in n)
            audio, sr = sf.read(io.BytesIO(z.read(name)), dtype="float32", always_2d=True)
            assert sr == 16000, sr
            path = OUT / f"{machine}_{condition}.ogg"
            sf.write(path, audio[:, 0], sr, format="OGG", subtype="VORBIS")
            print(f"{machine} {condition}: {name} -> {path.name} ({len(audio) / sr:.0f} s)", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
