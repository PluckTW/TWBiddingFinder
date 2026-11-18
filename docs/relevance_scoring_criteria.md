# 標案相關度評分標準（Plan B：Copilot in Excel）

> 來源：`model/text_classification.py` 的 `gpt_classification()` system prompt。
> 用途：當 app 內的自動評分失效時，可直接在 **Copilot in Excel** 用相同標準逐筆計算 score。
> 最後同步：2026/06（與 app 評分邏輯一致）。

---

## 一、評分定義

針對「政府標案標題（繁體中文）」判斷其與 **Molecular Devices 產品及其直接競爭對手**的相關程度，輸出 **0–100 的整數**：

- **100** = 高度相關（直接指名相關儀器或品牌型號）
- **0** = 完全不相關（與生物 / 儀器採購無關）
- 與生物學或儀器採購無關的標題，通常為低分。

### 涵蓋的產品與品牌

| 類別 | 品牌 / 型號 |
|---|---|
| **Molecular Devices（本品）** | 微盤分析儀：SpectraMax 系列；細胞影像：ImageXpress 系列 |
| BioTek / Agilent | Cytation、Epoch、Synergy |
| Thermo Fisher | VarioSkan、Multiskan |
| BMG Labtech | PHERAstar、CLARIOstar、FLUOstar |
| PerkinElmer / Revvity | EnVision、VICTOR |
| Tecan | plate readers（微盤儀） |
| ZEISS | cell imaging systems（細胞影像） |
| Bio-Rad | ddPCR、gel imaging（凝膠影像） |
| Biochrom | 分光光度計 |

### 評分範例（校準用）

| 標題 | 分數 |
|---|---|
| 流式細胞儀項目 | 80 |
| 超微量分光光度計壹台 | 80 |
| 化學試劑採購 | 30 |
| 數位病理影像教學管理系統*1式 | 0 |
| 螢光顯微鏡 | 70 |
| 分光光度計水質分析儀 | 70 |
| 多功能微盤分光光譜儀 | 100 |
| 基因定序採購 | 0 |
| SpectraMax微盤分析儀 | 100 |
| Cytation細胞影像讀盤儀 | 100 |
| PHERAstar FSX多功能微盤儀 | 100 |
| ImageXpress高內涵細胞影像系統 | 100 |
| ZEISS細胞影像系統 | 90 |
| VarioSkan酵素免疫分析儀 | 100 |
| 高解析質譜儀採購 | 0 |
| 試劑耗材採購 | 10 |

---

## 二、在 Copilot in Excel 使用

### 方法 A：`=COPILOT()` 函式（建議）

1. 把標案標題放在某一欄，例如 `A` 欄（`A2` 起）。
2. 在 `B1` 貼上「**三、Copilot 提示詞**」整段文字（當作指令）。
3. 在 `B2` 輸入下列公式並向下填滿：

   ```
   =COPILOT($B$1, A2)
   ```

   - `$B$1`：評分指令（鎖定不變）
   - `A2`：要評分的標題（逐列變動）

4. 結果欄會回傳 0–100 的整數。

### 方法 B：Copilot 對話框

選取標題範圍後，在 Copilot 側欄輸入「三、Copilot 提示詞」整段，並補一句：
「請對選取範圍每一列的標題輸出一個 0–100 的整數分數，新增到右側欄位。」

---

## 三、Copilot 提示詞（直接複製貼上）

```
You are a classification AI that determines the relevance of Traditional Chinese bidding titles to Molecular Devices' products (plate readers: SpectraMax series; cell imaging: ImageXpress series) and their direct competitors in the Taiwan market.
Competitors include: BioTek/Agilent (Cytation, Epoch, Synergy), Thermo Fisher (VarioSkan, Multiskan), BMG Labtech (PHERAstar, CLARIOstar, FLUOstar), PerkinElmer/Revvity (EnVision, VICTOR), Tecan plate readers, ZEISS cell imaging systems, Bio-Rad (ddPCR, gel imaging), Biochrom.
Output ONLY a confidence score as an integer from 0 to 100, without any additional text or symbols.
If the title is highly relevant, output 100.
If the title is completely irrelevant, output 0.
Titles unrelated to biology or instrument procurement will likely be irrelevant.
Score every title on its own merits: the same title must always get the same score, whatever other titles appear in the list.

Examples:
- '流式細胞儀項目' → 80
- '超微量分光光度計壹台' → 80
- '化學試劑採購' → 30
- '數位病理影像教學管理系統*1式' → 0
- '螢光顯微鏡' → 70
- '分光光度計水質分析儀' → 70
- '多功能微盤分光光譜儀' → 100
- '基因定序採購' → 0
- 'SpectraMax微盤分析儀' → 100
- 'Cytation細胞影像讀盤儀' → 100
- 'PHERAstar FSX多功能微盤儀' → 100
- 'ImageXpress高內涵細胞影像系統' → 100
- 'ZEISS細胞影像系統' → 90
- 'VarioSkan酵素免疫分析儀' → 100
- '高解析質譜儀採購' → 0
- '試劑耗材採購' → 10

Output format:
Only provide a number between 0 and 100, with no explanation or symbols.
```

---

## 四、app 內的分數一致性機制（2026/11 起）

LLM 對同一標題的分數不穩定（受同批其他標題影響）：歷史資料中有 21 個標題同時被評過 <70 與 ≥70，
造成「同一案招標時被排除、決標時才列入」。app 現在：

1. **同次執行去重**：招標＋決標標題合併、去除空白後每個標題只評一次，同標題必同分。
2. **低分複評**：第一輪 <70 的標題再以 5 題一批複評，取較高分（只會調高，不會調低）。
3. **同案取最高分**：同機關＋同案號、或同機關＋同標題，沿用本次與 Sheet 歷史中該案的最高分。
4. 模型 temperature 設為 0；若模型以 1 起算編號，自動校正避免分數錯位。

## 五、後續篩選

app 內的相關門檻為 **score ≥ 70**（`app.py` 的 `ai_threshold = 70`）。
在 Excel 中可用 `=IF(B2>=70,"相關","")` 或篩選功能，比照 app 的判定標準。
