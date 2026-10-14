# WZCR｜臺灣大學課程評分

## 公開原始碼版本

WZCR 是 WZUNAA Course Ratings 的縮寫。這是課程查詢與評分系統的獨立公開快照，保留目前的應用程式功能與官方公開課程資料，從新的 Git 歷史開始。

- 已停用的租屋資料種子 migration 保留編號，但不包含住宅地址、電話或座標資料。
- 聯絡信箱透過 `CONTACT_EMAIL` 設定；未設定時使用 `contact@example.com` 範例值。自行部署前請設定可公開的服務聯絡信箱。
- 不包含原站的部署專案識別碼、正式帳號資料、使用者評分紀錄或 OAuth 密鑰。`.openai/hosting.json` 只保留本機所需的資料庫綁定；部署到自己的專案時另行設定。
- `npm test` 會先從已提交的公開師資來源產生必要的種子檔案，再執行測試。

臺灣大學課程查詢與五項評分網站。首頁會直接進入課程目錄；訪客可依學校、系所、關鍵字與上／下學期篩選，登入後可新增課程並評分。

## 功能

- 學校選單共 42 所大學，其中 39 所已載入校方官方課表的課程與授課教師，合計約 20 萬門課程、42 萬筆教師授課紀錄。
- 尚未收錄課程的 3 所學校與原因記錄在 `db/place-name-course-report.generated.json`：臺藝大（全校課表需帳密登入）、空大（公開課程頁不提供授課教師）、高餐大（`classic.nkuht.edu.tw` 於稽核期間無法連線）。這些學校不以第三方網站或推測資料補齊。
- 課程以「課程＋授課教師」為評分卡；同一門課由多位教師授課時，各教師分開顯示與統計。
- 顯示教師全名、官方課程頁與官方系所網站；官方資料只採各校公開網站。
- 依學習收穫、作業量、考試難度、給分標準、點名頻率五項給予 0～100 分；每項都清楚標示高分代表的方向。
- 同帳號對同一課程與教師只保留一筆評分，重新送出採 UPSERT。
- Google OpenID Connect、PKCE、HttpOnly 工作階段與 D1 限流。
- 支援使用者新增課程，並保留官方來源與使用者來源標示。
- AdSense 設定、隱私權政策、服務條款與 `ads.txt`。

## 五項評分越高代表什麼

每一門課都以 0～100 分打五項，五項各自獨立顯示，網站不做加總、也不合併成單一分數。

| 評分項目 | 0 分 | 100 分 | 分數越高代表 | 方向 |
|---|---|---|---|---|
| 學習收穫 | 幾乎沒學到 | 學到很多 | 這門課帶來的知識與能力收穫越紮實 | 越高越有利 |
| 作業量 | 幾乎沒作業 | 作業非常多 | 作業與報告越多、越花時間 | 越高越吃重 |
| 考試難度 | 考試很簡單 | 考試很困難 | 考試越難、越不容易拿分 | 越高越吃重 |
| 給分標準 | 給分很嚴格 | 給分很甜 | 老師給分越寬鬆（越甜） | 越高越有利 |
| 點名頻率 | 幾乎不點名 | 幾乎堂堂點名 | 越常點名、缺席越容易被記錄 | 越高越吃重 |

高分不等於好課：只有「學習收穫」與「給分標準」是分數越高對修課者越有利；「作業量」「考試難度」「點名頻率」越高只代表這門課在該面向越吃重，適不適合仍取決於修課目標。

同一份文字同時出現在課程頁的「五項評分越高代表什麼」說明區、課程卡片各項目的滑鼠提示，以及評分表單的每個欄位下方，避免使用者反向理解分數。

## 架構

```text
Vinext / Next.js UI + 靜態資產
              ↓
Cloudflare Worker（頁面、OAuth 與 REST API）
              ↓
Cloudflare D1

Google OAuth → users / auth_sessions（不保存 Google token）
```

專案使用 Sites 管理部署，`.openai/hosting.json` 內的 D1 binding 由部署環境注入。網站沒有檔案上傳，因此 R2 binding 維持 `null`。

## D1 資料模型

- `universities`：學校基本資料。
- `users`：內部使用者與唯一 `google_sub`；Email 不公開。
- `auth_sessions`：工作階段 token 的 SHA-256 雜湊。
- `academic_departments`：官方網站所列系所、研究所與學位單位。
- `professors`：官方師資身分與來源；同校同名教師跨系所名稱以「／」合併。
- `professor_ratings`：歷史相容資料；目前前端主軸為課程評分。
- `courses`、`course_instructors`：官方歷史課程、上／下學期、授課教師與學校來源。
- `course_ratings`：唯一 `(user_id, course_id, instructor_name)` 的五項 0～100 課程評分。
- `api_rate_limits`：以使用者、動作、時間窗計數的基本濫用防護。
- `app_seed_versions`、`app_runtime_state`：大型官方種子與執行期 schema 狀態。

## 路由與 API

| Method | Path | 說明 |
|---|---|---|
| GET | `/` | 轉往 `/courses` |
| GET | `/courses` | 課程目錄與評分介面 |
| GET | `/api/universities` | 學校清單 |
| GET | `/api/departments?university_id=...` | 官方系所、學院、類型與來源 |
| GET | `/api/courses` | 依學校、系所、搜尋、上／下學期篩選；支援分頁 |
| POST | `/api/courses` | 登入後新增課程 |
| GET | `/api/courses/:id` | 課程、授課教師、官方連結與五項平均 |
| POST | `/api/courses/:id/rating` | 登入後 UPSERT 五項 0～100 課程評分 |
| GET | `/api/auth/session` | 目前登入狀態 |
| GET | `/api/auth/google/start` | 啟動 Google 登入 |
| GET | `/api/auth/google/callback` | Google OAuth callback |
| POST | `/api/auth/logout` | 登出 |

## 環境變數

複製 `.env.example` 為 `.env.local`：

```dotenv
NEXT_PUBLIC_ADSENSE_CLIENT=
NEXT_PUBLIC_ADSENSE_SLOT=

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:3000/api/auth/google/callback
```

AdSense 的公開 publisher ID 與「WZUNAA 課程列表」回應式廣告單元 ID 已有正式預設值；網站會載入官方驗證程式碼、在課程頁顯示該廣告單元，並提供 `/ads.txt`。如需切換到其他公開 ID，可透過 `NEXT_PUBLIC_ADSENSE_CLIENT` 與 `NEXT_PUBLIC_ADSENSE_SLOT` 覆寫。

正式 Google OAuth redirect URI：

```text
https://map.scmwcscr.com/api/auth/google/callback
```

Client Secret 只能設定為伺服器環境變數，不可使用 `NEXT_PUBLIC_` 前綴，也不可提交 Git。登入流程驗證 `state`、PKCE、Google JWKS、issuer、audience 與 Email verified；D1 不保存 access token、refresh token 或 Google 密碼。

## 本機開發

需求為 Node.js 22.13 以上。

```bash
npm install
npm run dev
```

開啟 `http://localhost:3000`。Vinext + Miniflare 會把本機 D1 SQLite 放在 `.wrangler/`；首次 API 請求會冪等建立核心資料表並匯入必要的學校、系所與師資資料。

## 官方課程匯入

- `scripts/import-official-course-history.py`：只從各校官方 HTTPS 網域建立歷史課程與來源快照。
- `scripts/import-nsysu-official-course-history.py`：從中山大學公開 `OPEN_CRS` 課程手冊逐一驗證完整系所目錄，匯入 106-1 至 115-1；不自動化或繞過學生歷史查詢的人工驗證碼。完整稽核記錄在 `db/nsysu-course-report.generated.json`。
- `scripts/import-place-name-universities.py`：補入全臺地名國立／市立大學的公開課表；以最新公開課表核對仍在校教師，並把受驗證碼或登入限制的學校明載於 `db/place-name-course-report.generated.json`。
  - `--only <學校代碼,…>` 只重跑指定學校，`--batch-id <批次名>` 指定新的 migration 批次；已提交的批次不會被覆寫，新批次的 `DELETE` 只作用在該批次真正匯入的學校，因此不會刪掉前一批次已發布的課程。
  - 課表把中文名稱、英文譯名與合班註記排在同一格時，只發布校方第一行的中文課名（`official_course_name`）。
- `scripts/import-four-private-universities.py`：匯入中原、淡江、元智與逢甲的校方公開資料。
- `db/course-seeds.generated.ts`：去重後課程主題；稽核資訊記錄在 `db/course-import-report.generated.json`。
- `scripts/discover-official-*.mjs`：從各校官方學術單位目錄尋找師資頁，只接受校方官方 HTTPS 子網域。
- `drizzle/0013_courses_and_course_ratings.sql` 之後的 course migration 建立課程模型並分段匯入官方資料。
- `drizzle/0050_remove_rentals.sql` 清理已停用功能的舊資料表與執行期標記，使正式 D1 只保留課程所需資料。

歷史課程匯入需要 Python 3 與 `openpyxl`：

```bash
npm run professors:discover
npm run professors:faculty-pages
npm run professors:extract
npm run professors:merge
npm run courses:official
npm run courses:nsysu
npm run courses:place-names
```

只補特定學校時：

```bash
python scripts/import-place-name-universities.py --only ntcu,ntue --batch-id place_name_course_batch_03
```

校方遇到人工驗證碼、非校方 API 或未公開可機讀歷史資料時，限制會保留在稽核報告，不以論壇、搜尋摘要、商業課程網站或其他第三方資料補齊。稽核報告中每所沒有課程的學校都必須帶著 `restricted` 或 `unreachable` 狀態與具體原因，測試會擋下「沒有課程也沒有理由」的學校。

各校課表原樣照收：系所欄位是校方課表自己印出的開課單位（部分學校為班級簡稱），課程名稱則只取校方第一行的中文課名。

## 品質檢查

```bash
npm test
npm run db:check
npm run lint
npm run build
npm audit
```

測試涵蓋 OAuth 安全、官方網域限制、師資身分合併、教師分卡、上／下學期、五項 0～100 評分驗證、使用者新增課程、大型 migration、D1 清理及正式建置路由。
