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
   - 只打包 1 個：自動生成 `D:\PackingTest\ComfyUI_windows_portable_(你的工作流名稱)\`
   - 打包 >= 2 個：自動生成 `D:\PackingTest\ComfyUI_windows_portable_Multi_Workflows\`
4. 選擇是否匯入非標準自訂的模型資料夾。
5. （重要選項）問你是否需打包完整的 `python_embeded`，如果目標電腦已安裝環境可選 `N` 節省巨大的 13 GB 空間。
6. 確認打包後等待程式智能複製完成。

---

## 💻 指令列模式 (Command Line Mode)

如果你熟悉命令提示字元或常需要大量打包，程式也支援直接代入參數：

```powershell
# 自動判定路徑並打包單個工作流
.\pack_workflow.bat -w "D:\MyOtherComfyUI\user\default\workflows\Gen1.json" -o "E:\OutputFolder"

# 自動判定路徑並同時把兩個以上的工作流聯合打包
.\pack_workflow.bat -w "Gen1.json" "Gen2.json" "Gen3.json" -o "E:\OutputFolder"

# 跳過所有 y/n 確認，直接開始打包
.\pack_workflow.bat -w "C:\path\to\workflow.json" -o "E:\OutputFolder" --yes

# 手動指定來源 (例如如果你的 JSON 放在桌面，無法讓系統自動從上層目錄推測 ComfyUI 環境時)
.\pack_workflow.bat -w "C:\Desktop\workflow.json" -o "E:\OutputFolder" -s "D:\Any\ComfyUI\Path"
```

---

## 🛠 功能特色與打包邏輯

打包工具包含了以下聰明的檢查邏輯：

1. **智能群組(Subgraph)與節點映射分析**：
   自動扒開最新的「雙擊打包的子群組 (Subgraph)」，找出當前工作流裡裡外外用到了哪些 Nodes 並自動打包特定的**自定義節點與內建節點對照**。
2. **自動篩選模型不重複複製**：
   自動掃描工作流當中的所有 `Checkpoint (大模型)`、`LoRA`、`VAE`、`ControlNet` 等模型名稱，並去主電腦的 `models` 目錄底下找尋路徑，只複製真的有被呼叫的模型檔 (即使多個工作流呼叫相同模型也只會複製一次節省空間)。
3. **剔除冗贅檔案**：
   大量的暫存檔 (`temp`)、舊產出圖 (`output`)、沒有入鏡的百G模型都不會被打包，大幅度縮減檔案體積！

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

1. 開啟打包完成的獨特 `ComfyUI_windows_portable...` 資料夾。
2. 點擊 `run_nvidia_gpu.bat` 啟動 ComfyUI 伺服器。
3. 把根目錄裡自動準備好的 `.json` 檔案拖曳到畫面上。
4. 按下 **Queue Prompt**，因為所有的模型跟套件都已包得完美無瑕，能順利無痛重現所有結果！
