# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "yt-dlp>=2026.10.21",  # a YouTube video's storyboard frames, without downloading the video
#   "pillow>=11.3",        # cutting the storyboards into contact sheets
# ]
# ///
"""frames sheet|strip ... --out DIR: what a YouTube video shows, as images to look at, without downloading the video.

  frames sheet VIDEO [VIDEO ...] --out DIR [--from T] [--to T]
      16 frames spread over the video (or over the stretch from T to T), 4 x 4: the setup at a glance (camera
      angle, a face on screen, the surface, a pile or a tray, the hands)
  frames strip STEP VIDEO [VIDEO ...] --out DIR [--from T] [--to T]
      a frame every STEP seconds, 120 small frames a page: what happens when, through a long video

VIDEO is a YouTube URL or video ID; T is 1:02:03, 4:15 or 255 (seconds). Each frame is labelled with its time. The
agent looks at a page with read_file on the .jpg and cites the times of the frames it saw.

The frames are YouTube's storyboards (the previews over the player's seek bar), listed by yt-dlp and cut with Pillow:
small (160 to 320 pixels wide), so they show the scene and the action, not small print. The wrapper runs it with `uv run --script` (inline metadata above).
yt-dlp needs a JavaScript runtime for YouTube (deno, found on PATH) and goes stale when YouTube changes:
`uv cache clean yt-dlp` makes the next run fetch the newest release.

Output: per video a header (title, channel, length, upload date, chapters), then one line per image written with
the times of its frames. A video this cannot show (not YouTube, private, removed, no storyboard) prints a line
starting BLOCKED: and exits 3: what it shows needs the laptop's real browser. Other errors exit 2.
"""
import argparse
import io
import pathlib
import re
import sys
import urllib.request

try:
    import yt_dlp
    from PIL import Image, ImageDraw
except ImportError as e:  # the venv predates this helper: never send the agent looking for another Python
    print(f"BLOCKED: this helper's runtime lacks {e.name} (uv could not build its environment); "
          "what the video shows needs the laptop's real browser")
    sys.exit(3)


def hms(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def seconds(s):
    """'1:02:03', '4:15' or '255' -> seconds."""
    t = 0.0
    for part in s.split(":"):
        t = t * 60 + float(part)
    return t


class Quiet:
    """yt-dlp's logger: its errors come back as exceptions and are printed once, as BLOCKED lines."""
    debug = info = warning = error = staticmethod(lambda msg: None)


def info(video):
    url = f"https://www.youtube.com/watch?v={video}" if re.fullmatch(r"[\w-]{11}", video) else video
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "cachedir": False,
            "logger": Quiet()}
    return yt_dlp.YoutubeDL(opts).extract_info(url, download=False)


class Storyboard:
    """YouTube's largest storyboard: sprite sheets of rows x columns frames, each sheet covering its duration."""

    def __init__(self, inf):
        sbs = sorted((f for f in inf.get("formats") or [] if str(f.get("format_id", "")).startswith("sb")
                      and f.get("fragments")), key=lambda f: -(f.get("width") or 0))
        if not sbs:
            raise LookupError("no storyboard")
        sb = sbs[0]
        self.frags, self.rows, self.cols = sb["fragments"], sb["rows"], sb["columns"]
        self.size = (sb["width"], sb["height"])
        self.starts, t = [], 0.0
        for fr in self.frags:
            self.starts.append(t)
            t += fr["duration"]
        self.total, self._cache = t, {}

    def spacing(self):
        """Seconds between frames: no stretch can be seen finer than this."""
        return self.frags[0]["duration"] / (self.rows * self.cols)

    def times(self):
        """Every frame's time."""
        for i, fr in enumerate(self.frags):
            per = fr["duration"] / (self.rows * self.cols)
            yield from (self.starts[i] + j * per for j in range(self.rows * self.cols) if j * per < fr["duration"])

    def frame(self, t):
        """(time, image) of the frame showing time t."""
        t = min(max(t, 0.0), self.total - 1e-3)
        i = max(k for k, s in enumerate(self.starts) if s <= t)
        per = self.frags[i]["duration"] / (self.rows * self.cols)
        j = min(int((t - self.starts[i]) / per), self.rows * self.cols - 1)
        if i not in self._cache:
            req = urllib.request.Request(self.frags[i]["url"], headers={"User-Agent": "Mozilla/5.0"})
            self._cache[i] = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert("RGB")
        img = self._cache[i]
        w, h = img.width // self.cols, img.height // self.rows
        return self.starts[i] + j * per, img.crop(((j % self.cols) * w, (j // self.cols) * h,
                                                    (j % self.cols + 1) * w, (j // self.cols + 1) * h))


def grid(frames, cols, tile, path):
    """Frames [(time, image)] in a grid, each labelled with its time."""
    tw, th = tile
    page = Image.new("RGB", (cols * tw, -(-len(frames) // cols) * (th + 12)), "white")
    d = ImageDraw.Draw(page)
    for k, (t, img) in enumerate(frames):
        x, y = (k % cols) * tw, (k // cols) * (th + 12)
        page.paste(img.resize(tile), (x, y + 12))
        d.text((x + 2, y), hms(t), fill="black")
    page.save(path, quality=82)




def span(sb, a):
    lo = seconds(a.start) if a.start else 0.0
    hi = min(seconds(a.end), sb.total) if a.end else sb.total
    if hi <= lo:
        raise ValueError(f"the stretch {hms(lo)} to {hms(hi)} is outside the video (length {hms(sb.total)})")
    tag = f"_{hms(lo).replace(':', '.')}-{hms(hi).replace(':', '.')}" if a.start or a.end else ""
    return lo, hi, tag


def sheet(inf, sb, a):
    lo, hi, tag = span(sb, a)
    frames = {}
    for k in range(16):  # a short stretch has fewer storyboard frames than 16: each one once
        t, img = sb.frame(lo + (hi - lo) * (k + 0.5) / 16)
        frames.setdefault(t, img)
    frames = list(frames.items())
    path = a.out / f"{inf['id']}{tag}-sheet.jpg"
    grid(frames, 4, sb.size, path)
    print(f"{path}  frames at {', '.join(hms(t) for t, _ in frames)}")


def strip(inf, sb, a):
    lo, hi, tag = span(sb, a)
    picked, nxt = [], lo
    for t in sb.times():
        if lo <= t <= hi and t >= nxt - 1e-6:
            picked.append(t)
            nxt = t + a.step
    frames = [sb.frame(t) for t in picked]
    for p in range(0, len(frames), 120):
        page = frames[p:p + 120]
        path = a.out / f"{inf['id']}{tag}-every{a.step:g}s-{p // 120 + 1}.jpg"
        grid(page, 12, (128, 72), path)
        print(f"{path}  {len(page)} frames, {hms(page[0][0])} to {hms(page[-1][0])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", type=pathlib.Path, required=True, help="folder for the images")
    common.add_argument("--from", dest="start", help="start of the stretch to look at (1:02:03, 4:15 or seconds)")
    common.add_argument("--to", dest="end", help="end of the stretch")
    s = sub.add_parser("sheet", parents=[common], help="16 frames spread over the video or the stretch")
    s.add_argument("videos", nargs="+")
    st = sub.add_parser("strip", parents=[common], help="a frame every STEP seconds")
    st.add_argument("step", type=float)
    st.add_argument("videos", nargs="+")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    worst = 0
    for video in a.videos:
        try:
            inf = info(video)
        except yt_dlp.utils.DownloadError as e:
            print(f"BLOCKED: yt-dlp cannot read {video}: {str(e).removeprefix('ERROR: ')[:300]}")
            worst = max(worst, 3)
            continue
        chapters = "; ".join(f"{hms(c['start_time'])} {c['title']}" for c in inf.get("chapters") or [])
        print(f"== {inf.get('title')} | {inf.get('channel')} | {hms(inf.get('duration') or 0)} | "
              f"uploaded {inf.get('upload_date')} | {inf.get('webpage_url')}"
              + (f"\nChapters: {chapters}" if chapters else ""))
        try:
            sb = Storyboard(inf)
        except LookupError:
            print(f"BLOCKED: {video} has no storyboard frames (not a YouTube video, or a live or very short one)")
            worst = max(worst, 3)
            continue
        print(f"Storyboard: {sb.size[0]}x{sb.size[1]} frames, one every {sb.spacing():.1f} s")
        try:
            (sheet if a.cmd == "sheet" else strip)(inf, sb, a)
        except Exception as e:  # one video's failure must not lose the others
            print(f"ERROR: {video}: {type(e).__name__}: {e}")
            worst = max(worst, 2)
    return worst


if __name__ == "__main__":
    sys.exit(main())
