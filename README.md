# ComfyUI Workflow Packer (智能工作流打包工具) 📦

這個工具專門用來將你「主電腦測試過完美無缺」的工作流，連同所有需要的 Custom Nodes、模型、ComfyUI 執行環境等，完整且「乾淨」地打包成一份可以在別台電腦上一鍵執行的便攜版 (Portable) 資料夾。

這套工具會**自動偵測並切換來源**，如果你的電腦上有多個版本的 ComfyUI (例如一個給 SDXL、一個給 SD3 等等)，它能根據工作流的位置自己找出它是屬於哪一個 ComfyUI 系統並且打包！

此外，它還支援 **多個工作流合併打包**，幫你產出一份具備展場 Demo 多種工作流所需的所有套件交集，且系統會為你自動建立獨立乾淨的不重複資料夾。

---

## 🚀 快速啟動 (互動模式)

1. 雙擊執行目錄下的 **`pack_workflow.bat`** 啟動打包介面。
2. 貼上你要打包的 **工作流檔案路徑**。
   - **單一打包**：直接將一個 JSON 檔案拖曳進命令提示字元視窗。
   - **一次把多個打包**：在檔案總管將你想要綜合打包的**多個 `.json` 檔案一起全選並拖曳進去**！(不同 JSON 間會以空格相隔，程式都能讀取解析)。
   > 💡 **自動偵測機制**：程式會尋找你第一個 `.json` 的上層路徑。如果往上找有發現到 `python_embeded` 或 `ComfyUI`，它就會**自動把這個環境認定為母體**並從裡面提取內容。
3. 輸入你要存放的 **打包目標外接硬碟根目錄**（例如：`D:\PackingTest`）。
4. **選擇打包模式**（見下方「打包模式」章節）。
5. 依模式不同，可能會被詢問：是否匯入非標準自訂的模型資料夾、是否打包完整的 `python_embeded`、是否保留 Git 版本資訊以便日後更新（見下方「代價：預設打包出去的版本無法更新」）。
6. 確認打包後等待程式智能複製完成。打包結束後，資料夾內會多一份 `manifest.json` / `manifest.txt`，記錄這次實際包了什麼、跳過了什麼、缺了什麼。

---

## 🧩 打包模式 (Packing Modes)

除了原本的完整打包，現在可以依需求選擇四種模式：

| 模式 | 用途 | 輸出型態 |
|---|---|---|
| **[1] 完整打包 (Full)** | 給完全沒有 ComfyUI 環境的人，隨插即用 | 完整的 `ComfyUI_windows_portable` 資料夾（可含 python_embeded） |
| **[2] 只打包 Custom Nodes** | 對方已經有 ComfyUI，只是缺了這個 workflow 用到的節點套件 | 一個乾淨的 `custom_nodes/` 資料夾 + 安裝說明，直接複製合併進對方的 `ComfyUI/custom_nodes/` |
| **[3] 只打包 Models** | 對方已經有 ComfyUI 跟節點，只是缺模型檔案 | 一個乾淨的 `models/` 資料夾 + 安裝說明，直接複製合併進對方的 `ComfyUI/models/` |
| **[4] 自訂組合 (Custom)** | 自行勾選要不要包含 python_embeded / ComfyUI 本體 / custom_nodes / models 任意組合 | 依勾選內容自動決定是完整資料夾還是合併用的 drop-in 資料夾 |

指令列也可以直接指定模式跳過選單：

```powershell
# 只打包這個 workflow 用到的 custom nodes
.\pack_workflow.bat -w "Gen1.json" -o "E:\Output" --mode custom_nodes --yes

# 只打包這個 workflow 用到的 models
.\pack_workflow.bat -w "Gen1.json" -o "E:\Output" --mode models --yes

# 自訂組合：只要 ComfyUI 本體 + custom nodes，不要 models、不要 python_embeded
.\pack_workflow.bat -w "Gen1.json" -o "E:\Output" --mode custom --yes `
    --include-comfyui-base --include-custom-nodes --no-include-models --no-include-python-embeded
```

---

## 💻 指令列模式 (Command Line Mode)

```powershell
# 自動判定路徑並打包單個工作流（完整打包）
.\pack_workflow.bat -w "D:\MyOtherComfyUI\user\default\workflows\Gen1.json" -o "E:\OutputFolder"

# 自動判定路徑並同時把兩個以上的工作流聯合打包
.\pack_workflow.bat -w "Gen1.json" "Gen2.json" "Gen3.json" -o "E:\OutputFolder"

# 跳過所有 y/n 確認，直接開始打包（未指定 --mode 時預設為完整打包）
.\pack_workflow.bat -w "C:\path\to\workflow.json" -o "E:\OutputFolder" --yes

# 手動指定來源 (例如如果你的 JSON 放在桌面，無法讓系統自動從上層目錄推測 ComfyUI 環境時)
.\pack_workflow.bat -w "C:\Desktop\workflow.json" -o "E:\OutputFolder" -s "D:\Any\ComfyUI\Path"

# 跳過 runtime 節點內省 (較快，但偵測準確度較低，主要用於除錯)
.\pack_workflow.bat -w "workflow.json" -o "E:\OutputFolder" --no-introspect

# 產出可更新 portable：會複製 update/ 並保留更新所需的 Git 資訊
.\pack_workflow.bat -w "workflow.json" -o "E:\OutputFolder" --yes --updatable

# 只讓 ComfyUI 本體可用官方 update\update_comfyui.bat 更新，不保留 custom_nodes 的 .git
.\pack_workflow.bat -w "workflow.json" -o "E:\OutputFolder" --yes --update-policy core

# 明確產出最小體積、不可更新的包
.\pack_workflow.bat -w "workflow.json" -o "E:\OutputFolder" --yes --no-updatable
```

主要參數：

| 參數 | 說明 |
|---|---|
| `-w / --workflow` | 一個或多個 workflow JSON 路徑 |
| `-o / --output` | 打包目標根目錄 |
| `-s / --source` | 手動指定來源 ComfyUI_windows_portable 路徑 |
| `-y / --yes` | 跳過所有確認提示（含手動節點解析提示） |
| `--mode` | `full` / `custom_nodes` / `models` / `custom` |
| `--include-python-embeded` / `--no-include-python-embeded` | (`--mode custom` 專用) |
| `--include-comfyui-base` / `--no-include-comfyui-base` | (`--mode custom` 專用) |
| `--include-custom-nodes` / `--no-include-custom-nodes` | (`--mode custom` 專用) |
| `--include-models` / `--no-include-models` | (`--mode custom` 專用) |
| `--no-introspect` | 跳過 runtime 節點內省，只用 regex/AST + 暴力搜尋偵測節點 |
| `--introspect-timeout` | 每個 custom_nodes 資料夾的內省逾時秒數（預設 25） |
| `--update-policy` | `none` / `core` / `core_and_nodes`。`core` 會複製 `update/` 並保留 `ComfyUI/.git`，讓官方 `update\update_comfyui.bat` 可更新 ComfyUI 本體；`core_and_nodes` 也會保留 custom nodes 的 `.git`，讓 ComfyUI-Manager 可更新有 Git repo 的節點。完整打包預設為 `core_and_nodes`，drop-in 模式預設為 `none` |
| `--updatable` / `--no-updatable` | `--updatable` 等同 `--update-policy core_and_nodes`；`--no-updatable` 等同 `--update-policy none` |
| `--keep-git` / `--no-keep-git` | 舊參數，為了相容既有腳本保留；等同 `--update-policy core_and_nodes` / `--update-policy none` |

---

## 🛠 功能特色與打包邏輯

打包工具包含了以下聰明的檢查邏輯：

1. **三層式自訂節點偵測（大幅降低漏包機率）**：
   - **Runtime 內省 (Introspection)**：實際在來源 ComfyUI 的 `python_embeded` 環境中，用獨立子行程 import 每一個 `custom_nodes` 資料夾，讀取真正的 `NODE_CLASS_MAPPINGS`。這能正確處理很多套件「動態組裝」節點清單的寫法（例如迴圈 `.update()`、跨檔案合併），這類寫法舊版的純 regex 掃描常常完全抓不到。
   - **Regex / AST 掃描**：當內省失敗或被跳過時的備援，會遞迴掃描資料夾內所有 `.py` 檔案，並偵測「動態組裝、無法靜態解析」的情況（會誠實標記為需要內省或手動處理，而不是靜默漏掉）。
   - **暴力字串搜尋**：最後一道防線，掃描所有檔案尋找節點名稱的字面字串。
   - 上述都無法解析時，會列出你本機的 `custom_nodes` 資料夾清單，讓你**手動指定**這個節點屬於哪個套件；你的選擇會被記住（存在 `%LOCALAPPDATA%\ComfyUIPacker\node_overrides.json`），下次同一台 ComfyUI 打包同一個節點時會自動套用，不會再問第二次。

2. **模型偵測不再只看副檔名**：
   除了掃描 `.safetensors / .ckpt / .gguf` 等常見模型副檔名外，針對已知的節點（如 ComfyUI-GGUF、KJNodes 等）額外用「widget 欄位對照表」判斷哪個欄位是模型檔名，即使該模型檔案在你電腦上**已經被刪除或本來就沒下載**，也會被正確列為「缺失」而不是被靜默忽略。

3. **自動篩選模型不重複複製**：
   自動掃描工作流當中的所有 `Checkpoint (大模型)`、`LoRA`、`VAE`、`ControlNet` 等模型名稱，並去主電腦的 `models` 目錄底下找尋路徑，只複製真的有被呼叫的模型檔 (即使多個工作流呼叫相同模型也只會複製一次節省空間)。

4. **剔除冗贅檔案**：
   大量的暫存檔 (`temp`)、舊產出圖 (`output`)、沒有入鏡的百G模型，以及 custom_nodes 資料夾內的 `.git`、`__pycache__`、`tests`、開發用虛擬環境等，預設都不會被打包，大幅度縮減檔案體積！
   > ✅ **完整打包預設會保留更新能力**。full portable 會複製來源的 `update/` 資料夾，並保留 `ComfyUI/.git` 與 custom nodes 的 `.git`，讓目標電腦可以使用官方 `update\update_comfyui.bat` 更新 ComfyUI；有 Git repo 的節點也可透過 ComfyUI-Manager 更新。若要做最小體積、不可更新的包，可加上 `--no-updatable` 或 `--update-policy none`。

5. **打包報告 (Manifest)**：
   每次打包完成（或中途失敗）都會在輸出資料夾留下 `manifest.json`（機器可讀）與 `manifest.txt`（人類可讀），完整記錄：每個 custom_nodes 資料夾是用哪種方式解析的、哪些節點無法解析、哪些模型缺失、實際打包大小等，方便事後稽核「這次到底包了什麼、漏了什麼」。

---

## ✨ 進階功能：遺失模型修補與下載 (Missing Models Auto-Downloader)

如果系統發現工作流模型檔案在主電腦的 `models/` 目錄中「找不到」(可能被誤刪、或是沒隨身攜帶到的模型)，它會在這一步驟把這些模型名稱與**預期存放路徑**列出來提供互動式的自動下載選擇：

- **[1] 略過 (Skip)**：如果你想要把打包隨身碟拿給別人後，讓他自己準備。
- **[2] URL 下載 (Direct)**：你可以去 Civitai 複製該下載連結貼上來，程式會顯示進度條並直接將它下載到**打包後的對應存放資料夾內**。
- **[3] HuggingFace Repo ID**：貼上來源庫名稱後 (例如 `black-forest-labs/FLUX.1-dev`)，程式會自己去它的主目錄或 `unet/` 等各種子頁面中翻找這個同名模型並將之納入。
- **[4] 自動搜尋 HuggingFace**：程式會用遺失的模型檔名搜尋 Hugging Face 最符合的前 5 名 Repo，輸入代號即可為便攜包直接下載補齊該模型！

> 💡 **注意：** 透過修補下載的所有模型，**只會存進你的目標打包隨身碟路徑中**，絕不會佔用你主電腦多餘的硬碟空間。

---

## 🎁 將隨身碟交給客戶/朋友後的操作指南

**完整打包 / 自訂組合（含 ComfyUI 本體）：**
1. 開啟打包完成的獨特 `ComfyUI_windows_portable...` 資料夾。
2. 點擊 `run_nvidia_gpu.bat` 啟動 ComfyUI 伺服器。
3. 把根目錄裡自動準備好的 `.json` 檔案拖曳到畫面上。
4. 按下 **Queue Prompt**，因為所有的模型跟套件都已包得完美無瑕，能順利無痛重現所有結果！

**只打包 Custom Nodes / 只打包 Models（drop-in 資料夾）：**
1. 打開資料夾內的 `README_INSTALL.txt`。
2. 依指示把 `custom_nodes/` 或 `models/` 底下的資料夾複製合併進對方已安裝好的 `ComfyUI/custom_nodes/` 或 `ComfyUI/models/`。
3. 重新啟動 ComfyUI，載入資料夾內附上的 `.json` workflow 即可。

---

## 🧱 專案結構

```
pack_workflow.py       # 進入點（薄殼，實際邏輯在 comfy_packer/ 裡）
pack_workflow.bat       # Windows 啟動器
comfy_packer/
    context.py           # 來源 ComfyUI 環境解析 (SourceEnv)
    constants.py          # 模型資料夾對照表、副檔名清單、忽略清單等
    workflow.py            # workflow JSON 解析 (API / UI 格式、subgraph)
    node_resolver.py        # 自訂節點偵測 (內省 + regex/AST + 暴力搜尋)
    node_overrides.py        # 手動節點解析的持久化快取
    node_schema.py             # 已知節點的模型欄位對照表
    model_resolver.py           # 模型檔案偵測與解析
    packing.py                   # 打包模式邏輯與實際複製流程
    manifest.py                   # 打包報告 (manifest.json/txt) 產生器
    downloader.py                  # 缺失模型互動下載
    cli.py                          # 指令列參數與互動選單
    ui.py                            # 主控台輸出小工具
    _introspect_node_folder.py       # 在來源 python_embeded 內執行的節點內省腳本
```
