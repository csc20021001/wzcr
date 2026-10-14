import type { Metadata } from 'next';
import Link from 'next/link';

const contactEmail = process.env.CONTACT_EMAIL?.trim() || 'contact@example.com';

export const metadata: Metadata = {
  title: '隱私權政策｜WZUNAA',
  description: 'WZUNAA 課程評分服務的資料蒐集、使用、保存與使用者權利說明。',
};

export default function PrivacyPage() {
  return (
    <main className="legal-page">
      <article className="legal-card">
        <Link className="legal-back" href="/courses">← 返回課程評分</Link>
        <p className="legal-kicker">WZUNAA · COURSE REVIEWS TAIWAN</p>
        <h1>隱私權政策</h1>
        <p className="legal-updated">最後更新：2026 年 9 月 2 日</p>

        <section>
          <h2>個資蒐集者與聯絡方式</h2>
          <p>本服務由 WZUNAA 營運。對個人資料蒐集、處理、利用或權利行使有疑問，請寄信至 <a href={`mailto:${contactEmail}`}>{contactEmail}</a>。</p>
        </section>

        <section>
          <h2>我們蒐集的資料</h2>
          <ul>
            <li>Google 登入提供的帳號識別碼、姓名、電子郵件地址與選用的大頭貼網址；本站不取得或保存 Google 密碼。</li>
            <li>你主動新增的課程資料、官方來源網址，以及對課程提交的學習收穫、作業量、考試難度、給分標準與點名頻率評分。</li>
            <li>工作階段、登入時間、請求時間與次數、錯誤及防止濫用所需的基本技術與安全紀錄。</li>
          </ul>
        </section>

        <section>
          <h2>蒐集目的</h2>
          <p>資料用於會員登入與身分確認、提供新增課程及評分功能、計算彙整結果、維護與更正課程資料、處理申訴、防止灌票與濫用、排除故障、維護服務安全，以及履行法律義務。除非另行告知並取得合法依據，不會把登入資料改作與上述目的無關的利用。</p>
        </section>

        <section>
          <h2>利用期間、地區、對象與方式</h2>
          <ul>
            <li><strong>期間：</strong>帳號存續、達成服務目的、依法保存，以及處理申訴或安全事件所必要的期間。</li>
            <li><strong>地區：</strong>臺灣及提供雲端、登入、分析或廣告服務的供應商實際處理資料之地區，可能包含境外處理。</li>
            <li><strong>對象：</strong>WZUNAA、受委託的服務供應商，以及依法有權要求提供資料的法院或主管機關。</li>
            <li><strong>方式：</strong>以自動化或非自動化方式蒐集、儲存、驗證、整理、統計、顯示、備份、安全監控及處理申訴。</li>
          </ul>
        </section>

        <section>
          <h2>公開範圍與使用者責任</h2>
          <p>課程評分以彙整分數與人數顯示，一般訪客不會看到評分者的 Email 或 Google 帳號識別碼。使用者新增的課程名稱、系所、授課教師與來源網址可能公開顯示。請勿提交私人電話、Email、住址、證件、金融、健康、家庭、個人成績或其他非必要個資，也不得公開他人秘密。</p>
        </section>

        <section>
          <h2>Google 登入、服務供應商與廣告</h2>
          <p>Google 登入由 Google 驗證。網站使用 Cloudflare 提供網站、資料庫與安全服務，並使用 Google AdSense 提供廣告。Google 及其合作夥伴可能依其服務條款與隱私政策處理 IP 位址、Cookie、裝置識別資訊、瀏覽器資訊、概略位置及廣告互動資料，以投放、衡量、限制與保護廣告；廣告是否個人化會依你的地區、同意狀態及設定而異。</p>
          <p>你可以閱讀 <a href="https://policies.google.com/technologies/partner-sites">Google 對合作夥伴網站資料使用方式的說明</a>，並在 <a href="https://adssettings.google.com/">Google 廣告設定</a>管理選擇，也可以透過瀏覽器限制或刪除 Cookie。本站依適用法令提供必要的告知與選擇。</p>
        </section>

        <section>
          <h2>是否必須提供資料及不提供的影響</h2>
          <p>你可以不登入並瀏覽公開課程與彙整評分；若不提供 Google 登入所需資料，將無法新增課程或提交評分。你也可以選擇不提交任何內容。</p>
        </section>

        <section>
          <h2>你的個資權利</h2>
          <p>你可依法請求查詢或閱覽、製給複製本、補充或更正、停止蒐集處理或利用，以及刪除個人資料。請寄信至 <a href={`mailto:${contactEmail}`}>{contactEmail}</a> 並說明請求內容；為避免冒用，本站得先合理確認身分。法律另有保存義務或處理爭議所必要時，可能無法立即或完整刪除，屆時會說明理由。</p>
        </section>

        <section>
          <h2>正確性、安全與事件處理</h2>
          <p>本站採取合理技術與管理措施保護資料，但網路傳輸與儲存無法保證絕對安全。若發生依法須通知的個資事件，本站會採取控制、調查與修復措施，並依適用法律通知受影響者或主管機關。</p>
        </section>

        <section>
          <h2>政策更新</h2>
          <p>本政策可能因功能、供應商或法令變更而調整，更新後會在本頁標示日期；重大變更會以合理方式提示。若不同意更新後的處理方式，請停止使用需登入的功能並聯絡本站行使權利。</p>
        </section>

        <nav className="legal-nav" aria-label="網站政策">
          <Link href="/courses">課程評分</Link>
          <Link href="/terms">服務條款</Link>
        </nav>
      </article>
    </main>
  );
}
