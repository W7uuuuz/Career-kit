"""录制 README / 抖音素材。

用法：
    python docs/examples/record_assets.py --all
    python docs/examples/record_assets.py --story
    python docs/examples/record_assets.py --loop
    python docs/examples/record_assets.py --stills

产物默认在 artifacts/media/（已 gitignore）：
- pain-16x9.mp4 / pain-9x16.mp4：25 秒痛点叙事
- pain-readme.gif：README 用压缩版
- loop-16x9.mp4 / loop-readme.gif：职业地图打卡闭环
- social-preview.png：1280×640
- stills/*.png：小红书 / X 静帧
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STORY = ROOT / "docs" / "examples" / "demo" / "story.html"
SOCIAL = ROOT / "docs" / "examples" / "demo" / "social-preview.html"
MAP = ROOT / "docs" / "examples" / "demo" / "career-map.html"
OUT = ROOT / "artifacts" / "media"
RAW = OUT / "raw"
STILLS = OUT / "stills"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# 7 个场景，总时长约 28 秒
SCENE_SECONDS = [2.8, 3.2, 4.0, 4.0, 4.2, 4.2, 4.0]

# README 短版：钩子 → 真实 JD → 同背景案例 → 差距诊断 → 下一步 → CTA
README_SCENES = [0, 2, 3, 4, 5, 6]
README_SECONDS = [2.6, 3.4, 3.2, 3.6, 3.6, 2.8]


def ensure_dirs() -> None:
    for directory in (OUT, RAW, STILLS):
        directory.mkdir(parents=True, exist_ok=True)


def _move_video(video, name: str) -> Path:
    target = OUT / f"{name}.webm"
    if target.exists():
        target.unlink()
    shutil.move(str(video.path()), str(target))
    return target


def record_story(
    name: str,
    width: int,
    height: int,
    scenes: list[int] | None = None,
    durations: list[float] | None = None,
) -> Path:
    scenes = scenes if scenes is not None else list(range(len(SCENE_SECONDS)))
    durations = durations if durations is not None else [SCENE_SECONDS[i] for i in scenes]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": width, "height": height},
            record_video_dir=str(RAW),
            record_video_size={"width": width, "height": height},
        )
        page = context.new_page()
        page.goto(STORY.as_uri())
        page.wait_for_timeout(500)
        for index, seconds in zip(scenes, durations):
            page.evaluate("(i) => window.showScene(i)", index)
            page.wait_for_timeout(int(seconds * 1000))
        # 给最后一帧和视频封装留足时间，避免 CTA 被截断
        page.wait_for_timeout(1800)
        video = page.video
        context.close()
        browser.close()
        return _move_video(video, name)


def record_loop() -> Path:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(RAW),
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()
        page.goto(MAP.as_uri())
        page.wait_for_timeout(1000)

        page.evaluate(
            "() => { const s = document.querySelector('input[type=range][data-action=percent]');"
            " if (s) s.scrollIntoView({block: 'center'}); }"
        )
        page.wait_for_timeout(900)
        page.evaluate(
            "() => { const s = document.querySelector('input[type=range][data-action=percent]');"
            " if (!s) return; s.value = s.max;"
            " s.dispatchEvent(new Event('input', {bubbles: true}));"
            " s.dispatchEvent(new Event('change', {bubbles: true})); }"
        )
        page.wait_for_timeout(1700)

        page.evaluate(
            "() => { const d = document.querySelector('details.task-detail');"
            " if (d) { d.open = true; d.scrollIntoView({block: 'center'}); } }"
        )
        page.wait_for_timeout(2300)

        for tab_index, wait_ms in ((1, 2200), (2, 2400), (0, 1800)):
            page.evaluate(
                "(i) => { const t = document.querySelectorAll('.tab'); if (t[i]) t[i].click(); }",
                tab_index,
            )
            page.wait_for_timeout(wait_ms)

        page.evaluate(
            "() => {"
            " const cta = document.createElement('div');"
            " cta.textContent = 'GitHub 搜 Career Kit';"
            " cta.style.cssText = 'position:fixed;left:50%;bottom:26px;"
            "transform:translateX(-50%);background:#4a6cf7;color:#fff;"
            "padding:14px 26px;border-radius:12px;"
            "font:700 18px -apple-system,Segoe UI,Microsoft YaHei,sans-serif;"
            "z-index:99999;box-shadow:0 12px 40px rgba(74,108,247,.5)';"
            " document.body.appendChild(cta);"
            "}"
        )
        page.wait_for_timeout(2500)

        video = page.video
        context.close()
        browser.close()
        return _move_video(video, "loop-16x9")


def capture_stills() -> None:
    names = ["hook", "input", "jd", "cases", "diagnosis", "task", "cta"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=2)
        for index, name in enumerate(names):
            page.goto(STORY.as_uri() + f"?scene={index}")
            page.wait_for_timeout(700)
            page.screenshot(path=str(STILLS / f"{index + 1:02d}-{name}.png"))
        browser.close()


def to_mp4(source: Path, target: Path) -> None:
    subprocess.run(
        [
            FFMPEG, "-y", "-i", str(source),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            "-movflags", "+faststart", str(target),
        ],
        check=True,
    )


def to_gif(source: Path, target: Path, width: int, fps: int) -> None:
    filters = (
        f"fps={fps},scale={width}:-1:flags=lanczos,"
        "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    )
    subprocess.run(
        [FFMPEG, "-y", "-i", str(source), "-vf", filters, "-loop", "0", str(target)],
        check=True,
    )


def make_social_preview() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1280, "height": 640}, device_scale_factor=2
        )
        page.goto(SOCIAL.as_uri())
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "social-preview.png"))
        browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="录制 Career Kit 演示素材")
    parser.add_argument("--all", action="store_true", help="录制全部素材")
    parser.add_argument("--story", action="store_true", help="只录 16:9 痛点视频")
    parser.add_argument("--vertical", action="store_true", help="只录 9:16 痛点视频")
    parser.add_argument("--loop", action="store_true", help="只录职业地图打卡")
    parser.add_argument("--stills", action="store_true", help="只截静帧")
    parser.add_argument("--readme", action="store_true", help="只录 README 短版 GIF")
    parser.add_argument("--convert-only", action="store_true", help="只做 mp4/gif 转换")
    args = parser.parse_args(argv)

    ensure_dirs()
    do_all = args.all or not any(
        [
            args.story,
            args.vertical,
            args.loop,
            args.stills,
            args.readme,
            args.convert_only,
        ]
    )

    if do_all or args.story:
        print("recording story 16:9 ...")
        to_mp4(record_story("pain-16x9", 1280, 720), OUT / "pain-16x9.mp4")
        to_gif(OUT / "pain-16x9.webm", OUT / "pain-readme.gif", 800, 8)

    if do_all or args.readme:
        print("recording readme cut ...")
        readme_webm = record_story(
            "readme-demo", 1280, 720, README_SCENES, README_SECONDS
        )
        to_mp4(readme_webm, OUT / "readme-demo.mp4")
        to_gif(readme_webm, OUT / "readme-demo.gif", 960, 10)

    if do_all or args.vertical:
        print("recording story 9:16 ...")
        to_mp4(record_story("pain-9x16", 1080, 1920), OUT / "pain-9x16.mp4")

    if do_all or args.loop:
        print("recording loop ...")
        to_mp4(record_loop(), OUT / "loop-16x9.mp4")
        to_gif(OUT / "loop-16x9.webm", OUT / "loop-readme.gif", 800, 8)

    if do_all or args.stills:
        print("capturing stills ...")
        capture_stills()
        make_social_preview()

    print("done:", OUT)
    for path in sorted(OUT.iterdir()):
        if path.is_file():
            print(" ", path.name, f"{path.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
