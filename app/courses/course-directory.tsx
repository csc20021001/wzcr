'use client';

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Check, ChevronDown, ExternalLink, GraduationCap, LogIn, Plus, Search, ShieldCheck, Star, X } from 'lucide-react';
import { AdSenseSlot } from '@/app/adsense';
import { universities } from '@/app/data';

type Course = {
  id: string;
  courseId: string;
  universityId: string;
  semester: '1' | '2';
  courseCode: string;
  name: string;
  department: string;
  officialSourceUrl: string;
  departmentSourceUrl: string;
  sourceType: 'official' | 'user';
  instructors: Array<{ name: string; officialSourceUrl: string }>;
  averageLearning: number | null;
  averageWorkload: number | null;
  averageExamDifficulty: number | null;
  averageGradingStandard: number | null;
  averageAttendanceFrequency: number | null;
  ratingCount: number;
};

type Department = {
  id: string;
  universityId: string;
  college: string;
  name: string;
  unitType: 'department' | 'institute' | 'program' | 'academic-unit';
  officialSourceUrl: string;
};

type AuthState = { user: { id: string; name: string } | null; googleConfigured: boolean };
type RatingScores = {
  learningScore: number;
  workloadScore: number;
  examDifficultyScore: number;
  gradingStandardScore: number;
  attendanceFrequencyScore: number;
};

const initialScores: RatingScores = {
  learningScore: 50,
  workloadScore: 50,
  examDifficultyScore: 50,
  gradingStandardScore: 50,
  attendanceFrequencyScore: 50,
};

const ratingDimensions: Array<{
  key: keyof RatingScores;
  label: string;
  low: string;
  high: string;
  hint: string;
  meaning: string;
  polarity: 'benefit' | 'intensity';
  averageKey: keyof Pick<Course, 'averageLearning' | 'averageWorkload' | 'averageExamDifficulty' | 'averageGradingStandard' | 'averageAttendanceFrequency'>;
}> = [
  {
    key: 'learningScore', label: '學習收穫', low: '幾乎沒學到', high: '學到很多',
    hint: '越高代表越能學到東西', polarity: 'benefit',
    meaning: '分數越高，代表這門課帶來的知識與能力收穫越紮實；0 分是整學期幾乎沒學到東西，100 分是收穫非常多。',
    averageKey: 'averageLearning',
  },
  {
    key: 'workloadScore', label: '作業量', low: '幾乎沒作業', high: '作業非常多',
    hint: '越高代表作業越多', polarity: 'intensity',
    meaning: '分數越高，代表作業與報告越多、越花時間；0 分是幾乎不用交作業，100 分是每週都被作業追著跑。',
    averageKey: 'averageWorkload',
  },
  {
    key: 'examDifficultyScore', label: '考試難度', low: '考試很簡單', high: '考試很困難',
    hint: '越高代表考試越難', polarity: 'intensity',
    meaning: '分數越高，代表考試越難、越不容易拿分；0 分是照著上課內容就能寫完，100 分是準備很久還是很難應付。',
    averageKey: 'averageExamDifficulty',
  },
  {
    key: 'gradingStandardScore', label: '給分標準', low: '給分很嚴格', high: '給分很甜',
    hint: '越高代表給分越寬鬆', polarity: 'benefit',
    meaning: '分數越高，代表老師給分越寬鬆（越甜）；0 分是給分非常嚴格，100 分是只要有做就給得很大方。',
    averageKey: 'averageGradingStandard',
  },
  {
    key: 'attendanceFrequencyScore', label: '點名頻率', low: '幾乎不點名', high: '幾乎堂堂點名',
    hint: '越高代表越常點名', polarity: 'intensity',
    meaning: '分數越高，代表越常點名、缺席越容易被記錄；0 分是整學期幾乎不點名，100 分是幾乎每堂都點。',
    averageKey: 'averageAttendanceFrequency',
  },
];

function toneForDepartment(department: string) {
  let hash = 0;
  for (const character of department) hash = (hash * 31 + character.codePointAt(0)!) >>> 0;
  return String(hash % 6);
}

export function CourseDirectory() {
  const [schoolId, setSchoolId] = useState('');
  const [search, setSearch] = useState('');
  const [department, setDepartment] = useState('');
  const [semester, setSemester] = useState('');
  const [departments, setDepartments] = useState<Department[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [auth, setAuth] = useState<AuthState>({ user: null, googleConfigured: false });
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [departmentsLoading, setDepartmentsLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [ratingTargetId, setRatingTargetId] = useState('');
  const [scores, setScores] = useState<RatingScores>(initialScores);
  const [submitting, setSubmitting] = useState(false);
  const [submissionOpen, setSubmissionOpen] = useState(false);
  const [courseSubmission, setCourseSubmission] = useState({ semester: '1', department: '', name: '', instructorName: '', officialSourceUrl: '' });
  const courseRequestVersion = useRef(0);
  const school = universities.find((item) => item.id === schoolId);

  useEffect(() => {
    fetch('/api/auth/session', { cache: 'no-store' })
      .then((response) => response.json() as Promise<AuthState>)
      .then(setAuth)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!schoolId) return;
    const controller = new AbortController();
    fetch(`/api/departments?university_id=${encodeURIComponent(schoolId)}`, { signal: controller.signal })
      .then(async (response) => {
        const data = await response.json() as { departments?: Department[]; error?: string };
        if (!response.ok) throw new Error(data.error || '系所資料載入失敗');
        setDepartments(data.departments ?? []);
      })
      .catch((caught) => {
        if (controller.signal.aborted) return;
        setDepartments([]);
        setMessage(caught instanceof Error ? caught.message : '系所資料載入失敗');
      })
      .finally(() => { if (!controller.signal.aborted) setDepartmentsLoading(false); });
    return () => controller.abort();
  }, [schoolId]);

  useEffect(() => {
    const requestVersion = ++courseRequestVersion.current;
    if (!schoolId) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      const params = new URLSearchParams({ university_id: schoolId });
      if (search.trim()) params.set('search', search.trim());
      if (department.trim()) params.set('department', department.trim());
      if (semester) params.set('semester', semester);
      params.set('limit', '36');
      params.set('offset', '0');
      fetch(`/api/courses?${params}`, { signal: controller.signal })
        .then(async (response) => {
          const data = await response.json() as { courses?: Course[]; total?: number; nextOffset?: number | null; error?: string };
          if (!response.ok) throw new Error(data.error || '課程資料載入失敗');
          if (requestVersion !== courseRequestVersion.current) return;
          setCourses(data.courses ?? []);
          setTotal(data.total ?? 0);
          setNextOffset(data.nextOffset ?? null);
          setMessage('');
        })
        .catch((caught) => {
          if (controller.signal.aborted || requestVersion !== courseRequestVersion.current) return;
          setCourses([]);
          setTotal(0);
          setNextOffset(null);
          setMessage(caught instanceof Error ? caught.message : '課程資料載入失敗');
        })
        .finally(() => { if (!controller.signal.aborted && requestVersion === courseRequestVersion.current) setLoading(false); });
    }, 220);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [department, schoolId, search, semester]);

  async function loadMore() {
    if (!schoolId || nextOffset === null || loadingMore) return;
    const requestVersion = courseRequestVersion.current;
    setLoadingMore(true);
    try {
      const params = new URLSearchParams({ university_id: schoolId, limit: '36', offset: String(nextOffset) });
      if (search.trim()) params.set('search', search.trim());
      if (department.trim()) params.set('department', department.trim());
      if (semester) params.set('semester', semester);
      const response = await fetch(`/api/courses?${params}`);
      const data = await response.json() as { courses?: Course[]; total?: number; nextOffset?: number | null; error?: string };
      if (!response.ok) throw new Error(data.error || '課程資料載入失敗');
      if (requestVersion !== courseRequestVersion.current) return;
      setCourses((current) => [...current, ...(data.courses ?? [])]);
      setTotal(data.total ?? total);
      setNextOffset(data.nextOffset ?? null);
    } catch (caught) {
      if (requestVersion !== courseRequestVersion.current) return;
      setMessage(caught instanceof Error ? caught.message : '課程資料載入失敗');
    } finally {
      if (requestVersion === courseRequestVersion.current) setLoadingMore(false);
    }
  }

  const departmentsByCollege = useMemo(() => {
    const grouped = new Map<string, Department[]>();
    for (const item of departments) grouped.set(item.college, [...(grouped.get(item.college) ?? []), item]);
    return [...grouped.entries()];
  }, [departments]);

  function openRating(course: Course) {
    if (!auth.user) {
      window.location.assign(`/api/auth/google/start?returnTo=${encodeURIComponent('/courses')}`);
      return;
    }
    setRatingTargetId(course.id);
    setScores(initialScores);
    setMessage('');
  }

  async function submitRating(event: FormEvent<HTMLFormElement>, course: Course) {
    event.preventDefault();
    setSubmitting(true);
    setMessage('');
    try {
      const response = await fetch(`/api/courses/${encodeURIComponent(course.id)}/rating`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(scores),
      });
      const data = await response.json() as { course?: Course; error?: string };
      if (!response.ok || !data.course) throw new Error(data.error || '評分失敗');
      setCourses((current) => current.map((item) => item.id === data.course!.id ? data.course! : item));
      setRatingTargetId('');
      setMessage('評分已更新。');
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : '評分失敗');
    } finally {
      setSubmitting(false);
    }
  }

  function updateScore(key: keyof RatingScores, value: string) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;
    const score = Math.min(100, Math.max(0, Math.round(parsed)));
    setScores((current) => ({ ...current, [key]: score }));
  }

  function openSubmission() {
    if (!schoolId) {
      setMessage('請先選擇學校。');
      return;
    }
    if (!auth.user) {
      window.location.assign(`/api/auth/google/start?returnTo=${encodeURIComponent('/courses')}`);
      return;
    }
    setCourseSubmission({ semester: semester || '1', department: department || departments[0]?.name || '', name: '', instructorName: '', officialSourceUrl: '' });
    setSubmissionOpen(true);
    setMessage('');
  }

  async function submitCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!schoolId) {
      setSubmissionOpen(false);
      setMessage('請先選擇學校。');
      return;
    }
    setSubmitting(true);
    setMessage('');
    try {
      const response = await fetch('/api/courses', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ universityId: schoolId, ...courseSubmission }),
      });
      const data = await response.json() as { course?: Course; error?: string };
      if (!response.ok || !data.course) throw new Error(data.error || '新增課程失敗');
      setCourses((current) => [data.course!, ...current]);
      setTotal((current) => current + 1);
      setSubmissionOpen(false);
      setMessage('課程已新增。');
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : '新增課程失敗');
    } finally {
      setSubmitting(false);
    }
  }

  function selectSchool(value: string) {
    courseRequestVersion.current += 1;
    setSchoolId(value);
    setSearch('');
    setDepartment('');
    setSemester('');
    setDepartments([]);
    setCourses([]);
    setTotal(0);
    setNextOffset(null);
    setLoadingMore(false);
    setRatingTargetId('');
    setSubmissionOpen(false);
    setCourseSubmission({ semester: '1', department: '', name: '', instructorName: '', officialSourceUrl: '' });
    setMessage('');
    setDepartmentsLoading(Boolean(value));
    setLoading(Boolean(value));
  }

  return <main className="professor-page">
    <div className="course-shell">
      <header className="professor-topbar">
        <a className="professor-brand" href="/courses" aria-label="WZUNAA 課程評分首頁"><span className="course-brand-mark">W</span><span>WZUNAA 課程評分</span></a>
        <div className="course-header-actions">
          {auth.user ? <small className="course-user-chip">{auth.user.name}</small> : <a className="course-login-button" href="/api/auth/google/start?returnTo=%2Fcourses"><LogIn size={14} />Google 登入</a>}
          <button className="course-add-button" type="button" onClick={openSubmission} disabled={!schoolId} title={schoolId ? undefined : '請先選擇學校'}><Plus size={15} />新增課程</button>
        </div>
      </header>

      <section className="professor-hero">
        <div className="professor-hero-copy">
          <p><Star size={14} fill="currentColor" />0–100 分課程評分</p>
          <h1>{school ? `${school.shortName}課程評分` : '先選擇一間學校'} <span aria-hidden="true">✦</span></h1>
          <strong>{school ? '五個面向，把每一門課的真實修課體感畫成一張卡。' : '從下方選擇學校，開始查詢課程與修課評價。'}</strong>
        </div>
        <div className="professor-source-note">
          <ShieldCheck size={17} />
          <span>資料來源以學校公開課程頁為準；課程與授課教師仍可能依校方最新公告調整。</span>
          <b>{!school ? '等待選校' : loading ? '正在整理課程' : `${total.toLocaleString('zh-TW')} 門課程`}</b>
        </div>
      </section>

      <details className="rating-legend">
        <summary>
          <span className="rating-legend-heading">
            <strong>五項評分越高代表什麼</strong>
            <small>0～100 分，五項各自獨立</small>
          </span>
          <span className="rating-legend-toggle">
            <span className="rating-legend-open-label">查看詳情</span>
            <span className="rating-legend-close-label">收起詳情</span>
            <ChevronDown size={17} aria-hidden="true" />
          </span>
        </summary>
        <div className="rating-legend-content">
          <p>每項都是 0～100 分，五項各自獨立顯示，不做加總、也不合併成單一分數。</p>
          <dl>
            {ratingDimensions.map((dimension) => <div key={`legend-${dimension.key}`}>
              <dt>{dimension.label}<em data-polarity={dimension.polarity}>{dimension.polarity === 'benefit' ? '越高越有利' : '越高越吃重'}</em></dt>
              <dd>
                <p>{dimension.meaning}</p>
                <small><span>0 分 · {dimension.low}</span><span>100 分 · {dimension.high}</span></small>
              </dd>
            </div>)}
          </dl>
          <p className="rating-legend-note">高分不等於好課：只有「學習收穫」與「給分標準」是分數越高對修課者越有利；「作業量」「考試難度」「點名頻率」越高只代表這門課在該面向越吃重，適不適合仍要看你自己的修課目標。</p>
        </div>
      </details>

      <section className="professor-controls" aria-label="課程篩選">
        <label><span>學校</span><select value={schoolId} onChange={(event) => selectSchool(event.target.value)}><option value="">請選擇學校</option>{universities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="course-search-field"><span><Search size={13} />搜尋課程、老師或系所</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={schoolId ? '輸入關鍵字' : '請先選擇學校'} disabled={!schoolId} /></label>
        <label><span>系所</span><select value={department} onChange={(event) => setDepartment(event.target.value)} disabled={!schoolId}><option value="">{schoolId ? `全部系所（${departmentsLoading ? '…' : departments.length}）` : '請先選擇學校'}</option>{departmentsByCollege.map(([college, units]) => <optgroup label={college} key={college}>{units.map((item) => <option value={item.name} key={item.id}>{item.name}</option>)}</optgroup>)}</select></label>
        <label><span>學期</span><select value={semester} onChange={(event) => setSemester(event.target.value)} disabled={!schoolId}><option value="">{schoolId ? '全部學期' : '請先選擇學校'}</option><option value="1">上學期</option><option value="2">下學期</option></select></label>
      </section>

      <AdSenseSlot />

      {message && <p className={`professor-message ${message === '評分已更新。' || message === '課程已新增。' ? 'is-success' : ''}`} role="status" aria-live="polite">{message}</p>}

      <section className="professor-grid" aria-label="課程列表" aria-busy={loading}>
        {!schoolId && <div className="professor-empty professor-school-prompt"><GraduationCap size={30} /><strong>請先選擇學校</strong><span>選好學校後，這裡會顯示該校的課程與五項評分。</span></div>}
        {schoolId && loading && <div className="professor-empty"><span className="loading-dot" />載入中</div>}
        {schoolId && !loading && courses.length === 0 && <div className="professor-empty"><GraduationCap size={28} /><strong>{department ? `${department}目前沒有已收錄課程` : '目前沒有符合條件的課程'}</strong><span>只有能由官方課程頁與現職師資名錄同時核對的課程才會顯示。</span></div>}
        {courses.map((course) => <article className={`professor-card ${ratingTargetId === course.id ? 'is-rating' : ''}`} data-tone={toneForDepartment(course.department)} key={course.id}>
          <div className="course-card-meta"><span>{course.department || school?.shortName || '未分類'}</span><small>{course.ratingCount} 人評分</small></div>
          <div className="course-card-heading"><small>{course.semester === '1' ? '上學期' : '下學期'}{course.sourceType === 'user' ? ' · 使用者新增' : ''}</small><h2>{course.name}</h2></div>
          <p className="course-instructors">授課：{course.instructors.map((instructor) => <span key={`${course.id}-${instructor.name}`}>{instructor.officialSourceUrl ? <a href={instructor.officialSourceUrl} target="_blank" rel="noreferrer">{instructor.name}<ExternalLink size={10} /></a> : instructor.name}</span>)}</p>
          <div className="course-official-links">{course.officialSourceUrl && <a href={course.officialSourceUrl} target="_blank" rel="noreferrer">{course.sourceType === 'official' ? '官方課程資料' : '參考來源'}<ExternalLink size={11} /></a>}{course.departmentSourceUrl && <a href={course.departmentSourceUrl} target="_blank" rel="noreferrer">官方系所網站<ExternalLink size={11} /></a>}</div>
          <dl className="professor-dimensions">
            {ratingDimensions.map((dimension) => {
              const value = course[dimension.averageKey];
              return <div key={dimension.key}><dt title={dimension.meaning}>{dimension.label}</dt><dd><span className="dimension-track" aria-hidden="true"><i style={{ width: `${value ?? 0}%` }} /></span><strong>{value === null ? '—' : value.toFixed(1)}</strong></dd></div>;
            })}
          </dl>
          {ratingTargetId !== course.id && <button className="open-rating-button" type="button" onClick={() => openRating(course)}>評這門課 <span aria-hidden="true">→</span></button>}
          {ratingTargetId === course.id && <form className="rating-form" onSubmit={(event) => void submitRating(event, course)}>
            <div className="rating-form-heading"><span>你的五項評分</span><button className="rating-close" type="button" onClick={() => setRatingTargetId('')} aria-label="關閉評分"><X size={15} /></button></div>
            {ratingDimensions.map((dimension) => <fieldset key={dimension.key}>
              <legend>{dimension.label}<small>{dimension.hint}</small></legend>
              <p className="dimension-meaning">{dimension.meaning}</p>
              <div className="dimension-scale">
                <input type="range" min="0" max="100" step="1" value={scores[dimension.key]} aria-label={`${course.name}的${dimension.label}分數`} aria-valuetext={`${scores[dimension.key]} 分`} onChange={(event) => updateScore(dimension.key, event.target.value)} />
                <label><span className="sr-only">{dimension.label}分數</span><input type="number" inputMode="numeric" min="0" max="100" step="1" value={scores[dimension.key]} onChange={(event) => updateScore(dimension.key, event.target.value)} /><span>分</span></label>
              </div>
              <small><span>0 {dimension.low}</span><span>100 {dimension.high}</span></small>
            </fieldset>)}
            <button className="rating-submit" type="submit" disabled={submitting}>{submitting ? '送出中…' : <><Check size={14} />送出五項課程評分</>}</button>
          </form>}
        </article>)}
      </section>

      {schoolId && !loading && courses.length > 0 && <div className="course-pagination"><span>已顯示 {courses.length}／{total} 門</span>{nextOffset !== null && <button type="button" onClick={() => void loadMore()} disabled={loadingMore}>{loadingMore ? '載入中…' : '顯示更多課程'}</button>}</div>}

      {submissionOpen && <div className="course-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSubmissionOpen(false); }}><form className="course-modal" role="dialog" aria-modal="true" aria-labelledby="course-modal-title" onSubmit={(event) => void submitCourse(event)}>
        <button className="course-modal-close" type="button" onClick={() => setSubmissionOpen(false)} aria-label="關閉"><X size={17} /></button>
        <p><Plus size={14} />新增課程</p><h2 id="course-modal-title">新增{school?.shortName ?? ''}課程</h2>
        <label>學期<select value={courseSubmission.semester} onChange={(event) => setCourseSubmission((current) => ({ ...current, semester: event.target.value }))}><option value="1">上學期</option><option value="2">下學期</option></select></label>
        <label>系所<select required value={courseSubmission.department} onChange={(event) => setCourseSubmission((current) => ({ ...current, department: event.target.value }))}><option value="">請選擇系所</option>{departmentsByCollege.map(([college, units]) => <optgroup label={college} key={college}>{units.map((item) => <option value={item.name} key={item.id}>{item.name}</option>)}</optgroup>)}</select></label>
        <label>課程名稱<input required minLength={2} maxLength={100} value={courseSubmission.name} onChange={(event) => setCourseSubmission((current) => ({ ...current, name: event.target.value }))} placeholder="例如：資料結構" /></label>
        <label>授課教師<input required minLength={2} maxLength={80} value={courseSubmission.instructorName} onChange={(event) => setCourseSubmission((current) => ({ ...current, instructorName: event.target.value }))} placeholder="請填寫教師全名" /></label>
        <label>學校官方來源（選填）<input type="url" value={courseSubmission.officialSourceUrl} onChange={(event) => setCourseSubmission((current) => ({ ...current, officialSourceUrl: event.target.value }))} placeholder="https://該校官方網站/..." /></label>
        <small>送出後，同學就能分享這門課的修課經驗。</small>
        <button className="course-modal-submit" type="submit" disabled={submitting || departments.length === 0}>{submitting ? '送出中…' : '新增課程'}</button>
      </form></div>}
      <footer className="course-footer"><span>WZUNAA</span><nav><a href="/privacy">隱私權政策</a><a href="/terms">服務條款</a></nav></footer>
    </div>
  </main>;
}
