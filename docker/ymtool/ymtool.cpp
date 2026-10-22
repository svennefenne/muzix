// ymtool: song info and WAV rendering for Atari ST .ym files, on top of StSound
// (https://github.com/arnaud-carre/StSound, MIT).
//
//   ymtool info   <file.ym>                 -> key=value lines
//   ymtool render <file.ym> <out.wav> <sec> -> 44.1 kHz 16-bit stereo WAV, looping as needed
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "StSoundLibrary.h"
// the loop point isn't exposed by the C API; read it from the player object
#define private public
#include "YmMusic.h"
#undef private

static void put16(FILE *f, unsigned v) { fputc(v & 255, f); fputc((v >> 8) & 255, f); }
static void put32(FILE *f, unsigned v) { put16(f, v & 0xffff); put16(f, v >> 16); }

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: ymtool info|render file.ym [out.wav seconds]\n"); return 2; }
    YMMUSIC *m = ymMusicCreate();
    if (!ymMusicLoad(m, argv[2])) { fprintf(stderr, "error: %s\n", ymMusicGetLastError(m)); return 1; }
    ymMusicInfo_t info;
    ymMusicGetInfo(m, &info);
    CYmMusic *ym = (CYmMusic *)m;
    if (!strcmp(argv[1], "info")) {
        printf("title=%s\nauthor=%s\ncomment=%s\ntype=%s\nduration_ms=%d\n",
               info.pSongName ? info.pSongName : "", info.pSongAuthor ? info.pSongAuthor : "",
               info.pSongComment ? info.pSongComment : "", info.pSongType ? info.pSongType : "",
               info.musicTimeInMs);
        if (ym->playerRate > 0 && ym->loopFrame >= 0 && ym->loopFrame < ym->nbFrame)
            printf("loop_ms=%d\n", (int)((long long)ym->loopFrame * 1000 / ym->playerRate));
        ymMusicDestroy(m);
        return 0;
    }
    if (strcmp(argv[1], "render") || argc < 5) { fprintf(stderr, "usage: ymtool render file.ym out.wav seconds\n"); return 2; }
    const int rate = 44100;
    long frames = (long)(atof(argv[4]) * rate);
    FILE *out = fopen(argv[3], "wb");
    if (!out) { perror(argv[3]); return 1; }
    fwrite("RIFF", 1, 4, out); put32(out, 36 + frames * 4); fwrite("WAVEfmt ", 1, 8, out);
    put32(out, 16); put16(out, 1); put16(out, 2); put32(out, rate); put32(out, rate * 4); put16(out, 4); put16(out, 16);
    fwrite("data", 1, 4, out); put32(out, frames * 4);
    ymMusicSetLoopMode(m, YMTRUE);
    ymMusicPlay(m);
    std::vector<ymsample> mono(4096);
    std::vector<short> stereo(8192);
    for (long done = 0; done < frames;) {
        int n = (int)((frames - done) < 4096 ? (frames - done) : 4096);
        ymMusicCompute(m, mono.data(), n);
        for (int i = 0; i < n; i++) stereo[2 * i] = stereo[2 * i + 1] = mono[i];
        fwrite(stereo.data(), 2, 2 * n, out);
        done += n;
    }
    fclose(out);
    ymMusicDestroy(m);
    return 0;
}
