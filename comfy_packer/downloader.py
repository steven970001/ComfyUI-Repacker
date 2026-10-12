"""Interactive missing-model download flow (direct URL / HuggingFace repo / HF search)."""

import json
import os
import sys
import urllib.request
import urllib.parse

from .ui import format_size


def _download_file(url, out_path):
    print(f"    ⬇️  Downloading from {url}...")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            total_size = int(response.info().get('Content-Length', 0))
            with open(out_path, 'wb') as f:
                downloaded = 0
                block_size = 8192
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    downloaded += len(buffer)
                    f.write(buffer)
                    if total_size > 0:
                        percent = min(100, int(downloaded * 100 / total_size))
                        sys.stdout.write(f"\r    [{percent:3d}%] \t{format_size(downloaded)} / {format_size(total_size)}")
                        sys.stdout.flush()
        print("\n    ✅ 下載完成!")
        return True
    except Exception as e:
        print(f"\n    ❌ 下載失敗: {e}")
        if os.path.exists(out_path):
            os.remove(out_path)
        return False


def interactive_download(missing_files, dest_dir):
    """Interactively help the user download missing models into the packaged output."""
    if not missing_files:
        return

    print("\n" + "─" * 60)
    print("  Step 6: 補齊缺失模型 (Downloading Missing Models)")
    print("─" * 60)

    for filename, rel_path in missing_files:
        print(f"\n  缺少模型: {filename}\n  內部預期路徑: {rel_path}")
        while True:
            print("    [1] 跳過 (Skip, 自己去下載)")
            print("    [2] 輸入直接下載網址 (Direct URL)")
            print("    [3] 輸入 HuggingFace Repo ID (例如: Kijai/flux-fp8)")
            print("    [4] 嘗試讓程式在 HuggingFace 自動搜尋")
            choice = input("    請選擇操作 [1-4]: ").strip()

            out_path = os.path.join(dest_dir, rel_path)

            if choice == "1":
                break
            elif choice == "2":
                url = input("    網址URL: ").strip()
                if url:
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    if _download_file(url, out_path):
                        break
            elif choice == "3":
                repo = input("    Repo ID: ").strip()
                if repo:
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    url = f"https://huggingface.co/{repo}/resolve/main/{urllib.parse.quote(filename)}"
                    print("    嘗試下載主目錄...")
                    if _download_file(url, out_path):
                        break
                    else:
                        print("    嘗試猜測子目錄 (例如 /unet, /vae, /lora)...")
                        found = False
                        for sub in ["unet", "vae", "loras", "checkpoints", "text_encoder", "diffusion_models"]:
                            sub_url = f"https://huggingface.co/{repo}/resolve/main/{sub}/{urllib.parse.quote(filename)}"
                            if _download_file(sub_url, out_path):
                                found = True
                                break
                        if found:
                            break
            elif choice == "4":
                print("    正在搜尋 HuggingFace...")
                query = os.path.splitext(filename)[0][:20]
                url = f"https://huggingface.co/api/models?search={urllib.parse.quote(query)}&limit=5"
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req) as resp:
                        results = json.loads(resp.read().decode())
                except Exception as e:
                    print(f"    搜尋失敗: {e}")
                    continue

                if not results:
                    print("    搜尋不到相關 Repo。")
                    continue

                print("    找到以下候選 Repo:")
                for i, r in enumerate(results):
                    print(f"      [{i+1}] {r['id']}")
                r_c = input("    請選擇 Repo [1-5] 或直接按 Enter 取消: ").strip()
                if r_c.isdigit() and 1 <= int(r_c) <= len(results):
                    repo = results[int(r_c)-1]['id']
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    dl_url = f"https://huggingface.co/{repo}/resolve/main/{urllib.parse.quote(filename)}"
                    if _download_file(dl_url, out_path):
                        break
                    else:
                        print("    下載失敗，該 Repo 中似乎沒有直接與此檔名一樣的檔案。")
