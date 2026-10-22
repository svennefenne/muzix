"""mutagen fix: WavPack files with non-standard sample rates (176.4/384 kHz)."""


def apply():
    """mutagen only knows WavPack's 15 table sample rates; other rates
    (176.4/384 kHz vinyl rips) live in an ID_SAMPLE_RATE metadata sub-block
    and made mutagen raise IndexError, so beets skipped those files."""
    from mutagen import wavpack as wv

    if getattr(wv.WavPackInfo, "_musicorg_patched", False):
        return

    def custom_rate(fileobj, start):
        fileobj.seek(start)
        head = fileobj.read(32)
        body = fileobj.read(int.from_bytes(head[4:8], "little") + 8 - 32)
        i = 0
        while i + 2 <= len(body):
            mid = body[i]
            if mid & 0x80:  # ID_LARGE: 24-bit size
                size, i = int.from_bytes(body[i + 1:i + 4], "little") * 2, i + 4
            else:
                size, i = body[i + 1] * 2, i + 2
            if mid & 0x3F == 0x27:  # ID_SAMPLE_RATE
                return int.from_bytes(body[i:i + 3], "little")
            i += size
        return 0

    def init(self, fileobj):
        start = fileobj.tell()
        try:
            header = wv._WavPackHeader.from_fileobj(fileobj)
        except wv.WavPackHeaderError:
            raise wv.WavPackHeaderError("not a WavPack file")
        self.version = header.version
        self.channels = bool(header.flags & 4) or 2
        idx = (header.flags >> 23) & 0xF
        if idx < len(wv.RATES):
            self.sample_rate = wv.RATES[idx]
        else:
            pos = fileobj.tell()
            self.sample_rate = custom_rate(fileobj, start)
            fileobj.seek(pos)
        self.bits_per_sample = ((header.flags & 3) + 1) * 8
        if (header.flags >> 31) & 1:  # DSD
            self.sample_rate *= 4
            self.bits_per_sample = 1
        if header.total_samples == -1 or header.block_index != 0:
            samples = header.block_samples
            while True:
                fileobj.seek(header.block_size - 32 + 8, 1)
                try:
                    header = wv._WavPackHeader.from_fileobj(fileobj)
                except wv.WavPackHeaderError:
                    break
                samples += header.block_samples
        else:
            samples = header.total_samples
        self.length = float(samples) / self.sample_rate if self.sample_rate else 0.0

    wv.WavPackInfo.__init__ = init
    wv.WavPackInfo._musicorg_patched = True


apply()
