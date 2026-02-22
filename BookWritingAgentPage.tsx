import React, { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Book, List, Download, Save, Edit3, Wand2, ChevronRight, ChevronLeft, FileText } from 'lucide-react';
import axiosInstance from '@/lib/api/client';
import toast from 'react-hot-toast';

type Step = 'concept' | 'outline' | 'drafting' | 'export';
type Mode = 'toc' | 'refine_toc' | 'chapter' | 'export';

interface OutlineChapter {
  number: number;
  title: string;
  bullet_points: string[];
}

interface OutlineData {
  synopsis: string;
  chapters: OutlineChapter[];
}

interface AgentOutputs {
  status?: 'success' | 'error';
  errors?: string[];
  warnings?: string[];
  trace_id?: string;
  outline?: OutlineData;
  chapter?: { number: number; title: string; content: string; summary?: string };
  pdf_base64?: string;
  pdf_filename?: string;
  docx_base64?: string;
  docx_filename?: string;
}

interface BookState {
  title: string;
  genre: string;
  audience: string;
  language: string;
  tone: string;
  length: number;
  outline: OutlineData | null;
  currentChapterId: number | null;
  chaptersContent: Record<number, string>;
  backendProjectId: string | null;
  updatedAt: string;
}

interface BackendProject {
  id: string;
  title?: string;
  genre?: string;
  target_audience?: string;
  language?: string;
  tone?: string;
  target_word_count?: number;
  outline_json?: OutlineData;
}

interface BackendChapter {
  id: string;
  project: string;
  number: number;
  title: string;
  content: string;
  status?: string;
}

interface AgentRunRecord {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  mode: Mode;
  output_payload?: AgentOutputs;
  error_message?: string;
  trace_id?: string;
}

type SetBookState = React.Dispatch<React.SetStateAction<BookState>>;

const AGENT_ID = 'eef314c9-183b-4d87-9d6c-88815a72be15';
const STORAGE_KEY = 'book_agent_ui_state_v3';

const DEFAULT_STATE: BookState = {
  title: '',
  genre: 'Non-fiction',
  audience: 'General readers',
  language: 'English',
  tone: 'Informative',
  length: 3000,
  outline: null,
  currentChapterId: null,
  chaptersContent: {},
  backendProjectId: null,
  updatedAt: new Date().toISOString(),
};

const readState = (): BookState => {
  if (typeof window === 'undefined') return DEFAULT_STATE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_STATE;
    const parsed = JSON.parse(raw) as Partial<BookState>;
    return {
      ...DEFAULT_STATE,
      ...parsed,
      outline: parsed.outline || null,
      chaptersContent: parsed.chaptersContent || {},
      backendProjectId: parsed.backendProjectId || null,
    };
  } catch {
    return DEFAULT_STATE;
  }
};

const words = (text: string) => (text.trim() ? text.trim().split(/\s+/).length : 0);
const isSuccess = (o: AgentOutputs) => (o.status ? o.status === 'success' : Boolean(o.outline || o.chapter || o.pdf_base64 || o.docx_base64));
const commonInputs = (s: BookState) => ({
  book_title: s.title,
  genre: s.genre,
  target_audience: s.audience,
  language: s.language,
  tone: s.tone,
  book_length: s.length,
});

const API_PATHS = {
  projectCreate: ['/api/books/projects/', '/books/projects/'],
  projectDetail: (projectId: string) => [`/api/books/projects/${projectId}/`, `/books/projects/${projectId}/`],
  projectChapters: (projectId: string) => [`/api/books/projects/${projectId}/chapters/`, `/books/projects/${projectId}/chapters/`],
  chapterList: ['/api/books/chapters/', '/books/chapters/'],
  chapterDetail: (chapterId: string) => [`/api/books/chapters/${chapterId}/`, `/books/chapters/${chapterId}/`],
  runCreate: ['/api/agents/runs/', '/agents/runs/'],
  runDetail: (runId: string) => [`/api/agents/runs/${runId}/`, `/agents/runs/${runId}/`],
  legacyExecute: [`/api/agents/${AGENT_ID}/execute`, `/agents/${AGENT_ID}/execute`],
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function requestWithFallback<T>(
  method: 'get' | 'post' | 'patch',
  paths: string[],
  config: { data?: unknown; params?: Record<string, unknown> } = {}
): Promise<T> {
  let lastError: unknown;
  for (const path of paths) {
    try {
      const response = await axiosInstance.request<T>({
        method,
        url: path,
        data: config.data,
        params: config.params,
      });
      return response.data;
    } catch (error: unknown) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      lastError = error;
      if (status === 404) {
        continue;
      }
      throw error;
    }
  }
  throw lastError || new Error('No compatible API endpoint found.');
}

function toOutputs(payload: unknown): AgentOutputs {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Invalid agent response payload.');
  }
  const objectPayload = payload as Record<string, unknown>;
  const outputs = (objectPayload.outputs || objectPayload.output_payload || objectPayload) as AgentOutputs;
  if (typeof outputs !== 'object' || outputs === null) {
    throw new Error('Invalid agent outputs.');
  }
  return outputs;
}

async function ensureProject(state: BookState, setState: SetBookState): Promise<string> {
  const payload = {
    title: state.title,
    genre: state.genre,
    target_audience: state.audience,
    language: state.language,
    tone: state.tone,
    target_word_count: state.length,
    outline_json: state.outline || {},
  };

  if (state.backendProjectId) {
    const project = await requestWithFallback<BackendProject>('patch', API_PATHS.projectDetail(state.backendProjectId), { data: payload });
    return project.id || state.backendProjectId;
  }

  const created = await requestWithFallback<BackendProject>('post', API_PATHS.projectCreate, { data: payload });
  if (!created?.id) {
    throw new Error('Failed to create backend project.');
  }

  setState((prev) => ({
    ...prev,
    backendProjectId: created.id,
    updatedAt: new Date().toISOString(),
  }));

  return created.id;
}

async function syncChapters(projectId: string, state: BookState): Promise<void> {
  if (!state.outline?.chapters?.length) {
    return;
  }

  let existingByNumber = new Map<number, BackendChapter>();
  try {
    const existing = await requestWithFallback<BackendChapter[]>('get', API_PATHS.chapterList, { params: { project_id: projectId } });
    existingByNumber = new Map(existing.map((chapter) => [chapter.number, chapter]));
  } catch {
    existingByNumber = new Map();
  }

  for (const chapter of state.outline.chapters) {
    const content = state.chaptersContent[chapter.number] || '';
    const existing = existingByNumber.get(chapter.number);
    if (existing) {
      await requestWithFallback<BackendChapter>('patch', API_PATHS.chapterDetail(existing.id), {
        data: { title: chapter.title, content },
      });
    } else {
      await requestWithFallback<BackendChapter>('post', API_PATHS.projectChapters(projectId), {
        data: {
          number: chapter.number,
          title: chapter.title,
          content,
          summary: '',
        },
      });
    }
  }
}

async function runViaAsyncApi(mode: Mode, state: BookState, setState: SetBookState, inputs: Record<string, unknown>): Promise<AgentOutputs> {
  const projectId = await ensureProject(state, setState);
  if (mode === 'export') {
    await syncChapters(projectId, state);
  }

  const run = await requestWithFallback<AgentRunRecord>('post', API_PATHS.runCreate, {
    data: { project_id: projectId, mode, inputs },
  });
  if (!run?.id) {
    throw new Error('Run creation failed.');
  }

  let currentRun = run;
  const started = Date.now();
  while (currentRun.status === 'queued' || currentRun.status === 'running') {
    if (Date.now() - started > 240000) {
      throw new Error('Run timed out. Please retry.');
    }
    await sleep(1200);
    currentRun = await requestWithFallback<AgentRunRecord>('get', API_PATHS.runDetail(run.id));
  }

  if (currentRun.status === 'failed') {
    throw new Error(currentRun.error_message || 'Async run failed.');
  }
  if (!currentRun.output_payload) {
    throw new Error('Run completed without output payload.');
  }

  const outputs = toOutputs(currentRun);
  if (!outputs.trace_id && currentRun.trace_id) {
    outputs.trace_id = currentRun.trace_id;
  }
  return outputs;
}

async function runViaLegacyExecute(inputs: Record<string, unknown>): Promise<AgentOutputs> {
  const payload = await requestWithFallback<unknown>('post', API_PATHS.legacyExecute, { data: { inputs } });
  return toOutputs(payload);
}

function getErrorMessage(error: unknown, fallback: string): string {
  const responseData = (error as { response?: { data?: unknown } })?.response?.data;
  if (typeof responseData === 'string' && responseData.trim()) {
    return responseData;
  }
  if (responseData && typeof responseData === 'object') {
    const detail = (responseData as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
  }
  const message = (error as { message?: string })?.message;
  if (typeof message === 'string' && message.trim()) {
    return message;
  }
  return fallback;
}

function downloadBase64(base64Data: string, filename: string, mime: string) {
  const a = document.createElement('a');
  a.href = `data:${mime};base64,${base64Data}`;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

const BookWritingAgentPage: React.FC = () => {
  const [currentStep, setCurrentStep] = useState<Step>('concept');
  const [isSidebarOpen, setSidebarOpen] = useState(true);
  const [bookState, setBookState] = useState<BookState>(() => readState());
  const [transport, setTransport] = useState<'auto' | 'async' | 'legacy'>('auto');
  const [lastRun, setLastRun] = useState<string>('No runs yet.');

  useEffect(() => {
    if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, JSON.stringify(bookState));
  }, [bookState]);

  const progress = useMemo(() => {
    const total = bookState.outline?.chapters.length || 0;
    const done = (bookState.outline?.chapters || []).filter((c) => Boolean(bookState.chaptersContent[c.number]?.trim())).length;
    return { total, done, pct: total ? Math.round((done / total) * 100) : 0 };
  }, [bookState.outline, bookState.chaptersContent]);

  const canOutline = Boolean(bookState.title.trim());
  const canDraft = Boolean(bookState.outline?.chapters.length);
  const steps: Array<{ id: Step; label: string; icon: React.ReactNode; enabled: boolean }> = [
    { id: 'concept', label: 'Concept', icon: <Book size={18} />, enabled: true },
    { id: 'outline', label: 'Outline', icon: <List size={18} />, enabled: canOutline },
    { id: 'drafting', label: 'Drafting', icon: <Edit3 size={18} />, enabled: canDraft },
    { id: 'export', label: 'Export', icon: <Download size={18} />, enabled: canDraft },
  ];

  const logRun = (mode: Mode, outputs: AgentOutputs) => {
    const msg = `${new Date().toLocaleTimeString()} | ${mode} | ${isSuccess(outputs) ? 'success' : 'error'}${outputs.trace_id ? ` | trace ${outputs.trace_id}` : ''}`;
    setLastRun(msg);
    if (outputs.warnings?.length) toast(outputs.warnings[0], { icon: '⚠️' });
  };

  const executeAgent = async (mode: Mode, inputs: Record<string, unknown>): Promise<AgentOutputs> => {
    try {
      setLastRun(`${new Date().toLocaleTimeString()} | ${mode} | running | async`);
      const outputs = await runViaAsyncApi(mode, bookState, setBookState, inputs);
      setTransport('async');
      return outputs;
    } catch (asyncError) {
      const status = (asyncError as { response?: { status?: number } })?.response?.status;
      const message = (asyncError as { message?: string })?.message || '';
      const shouldFallback = status === 404 || message.includes('No compatible API endpoint found');
      if (!shouldFallback) {
        throw asyncError;
      }
      console.warn('Async API endpoints unavailable, falling back to legacy execute endpoint.', asyncError);
      setLastRun(`${new Date().toLocaleTimeString()} | ${mode} | fallback | legacy`);
      const outputs = await runViaLegacyExecute(inputs);
      setTransport('legacy');
      return outputs;
    }
  };

  const renderStep = () => {
    if (currentStep === 'concept') {
      return (
        <ConceptStep
          bookState={bookState}
          setBookState={setBookState}
          onNext={() => setCurrentStep('outline')}
          onRun={logRun}
          executeAgent={executeAgent}
        />
      );
    }
    if (currentStep === 'outline') {
      return (
        <OutlineStep
          bookState={bookState}
          setBookState={setBookState}
          onNext={() => setCurrentStep('drafting')}
          onRun={logRun}
          executeAgent={executeAgent}
        />
      );
    }
    if (currentStep === 'drafting') {
      return (
        <DraftingStep
          bookState={bookState}
          setBookState={setBookState}
          onNext={() => setCurrentStep('export')}
          onRun={logRun}
          executeAgent={executeAgent}
        />
      );
    }
    return <ExportStep bookState={bookState} onRun={logRun} executeAgent={executeAgent} />;
  };

  return (
    <div className="flex h-[calc(100vh-64px)] overflow-hidden bg-[#f0e8d7] text-[#1f3134]">
      <motion.aside initial={{ width: 250 }} animate={{ width: isSidebarOpen ? 250 : 84 }} className="border-r border-[#264341]/25 bg-[#1f3c3f] text-[#d4e3db]">
        <div className="flex items-center justify-between border-b border-[#86a89d]/20 p-4">
          {isSidebarOpen ? <div><div className="text-lg font-semibold text-[#f5ebc8]">Book Foundry</div><div className="text-xs text-[#9ab3aa]">Writer Studio</div></div> : <div className="mx-auto text-sm font-semibold">BF</div>}
          <button onClick={() => setSidebarOpen((v) => !v)} className="rounded-lg p-2 hover:bg-[#2d5150]">{isSidebarOpen ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}</button>
        </div>
        <nav className="space-y-2 p-3">
          {steps.map((s) => (
            <button
              key={s.id}
              onClick={() => (s.enabled ? setCurrentStep(s.id) : toast.error('Complete previous steps first.'))}
              className={`flex w-full items-center rounded-xl px-3 py-3 ${currentStep === s.id ? 'border border-[#e5c876]/40 bg-[#e5c876]/15 text-[#f8e9b3]' : s.enabled ? 'hover:bg-[#2a4b4b]' : 'cursor-not-allowed text-[#7f9890]'}`}
            >
              <span className="mr-3">{s.icon}</span>{isSidebarOpen && <span className="text-sm">{s.label}</span>}
            </button>
          ))}
        </nav>
        {isSidebarOpen && <div className="mx-3 mt-2 rounded-xl border border-[#8eaea4]/20 bg-[#2a4b4c] p-3 text-xs"><div className="mb-1">Draft progress: {progress.pct}%</div><div>{progress.done}/{progress.total || 0} chapters complete</div></div>}
      </motion.aside>

      <main className="relative flex-1 overflow-y-auto p-4 md:p-6">
        <div className="mb-4 rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-4">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold">{bookState.title || 'Untitled Project'}</h1>
              <p className="text-sm text-[#5a6c70]">{bookState.genre} | {bookState.language} | {bookState.tone} | target {bookState.length.toLocaleString()} words</p>
            </div>
            <div className="text-xs text-[#526568]">
              <div>Updated: {new Date(bookState.updatedAt).toLocaleString()}</div>
              <div>Execution: {transport}{bookState.backendProjectId ? ` | project ${bookState.backendProjectId.slice(0, 8)}...` : ''}</div>
              <div>{lastRun}</div>
            </div>
          </div>
        </div>
        <AnimatePresence mode="wait">
          <motion.div key={currentStep} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.22 }}>
            {renderStep()}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
};

const ConceptStep: React.FC<{
  bookState: BookState;
  setBookState: SetBookState;
  onNext: () => void;
  onRun: (mode: Mode, outputs: AgentOutputs) => void;
  executeAgent: (mode: Mode, inputs: Record<string, unknown>) => Promise<AgentOutputs>;
}> = ({ bookState, setBookState, onNext, onRun, executeAgent }) => {
  const [loading, setLoading] = useState(false);
  const save = <K extends keyof BookState>(k: K, v: BookState[K]) => setBookState((p) => ({ ...p, [k]: v, updatedAt: new Date().toISOString() }));
  const generate = async () => {
    if (!bookState.title.trim()) return toast.error('Book title is required.');
    setLoading(true);
    try {
      const inputs = { mode: 'toc', ...commonInputs(bookState) };
      const outputs = await executeAgent('toc', inputs);
      onRun('toc', outputs);
      if (isSuccess(outputs) && outputs.outline) {
        setBookState((p) => ({ ...p, outline: outputs.outline || null, currentChapterId: outputs.outline?.chapters[0]?.number || null, updatedAt: new Date().toISOString() }));
        toast.success('Outline generated.');
        onNext();
      } else toast.error(outputs.errors?.[0] || 'Generation failed.');
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to contact agent.'));
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="mx-auto grid max-w-5xl grid-cols-1 gap-6 xl:grid-cols-5">
      <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-6 xl:col-span-3">
        <h2 className="mb-4 text-2xl font-semibold">Concept Studio</h2>
        <div className="space-y-4">
          <InputGroup label="Book Title" value={bookState.title} onChange={(v) => save('title', v)} placeholder="e.g. Operational Clarity for Teams" />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <InputGroup label="Genre" value={bookState.genre} onChange={(v) => save('genre', v)} />
            <InputGroup label="Audience" value={bookState.audience} onChange={(v) => save('audience', v)} />
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <InputGroup label="Language" value={bookState.language} onChange={(v) => save('language', v)} />
            <InputGroup label="Tone" value={bookState.tone} onChange={(v) => save('tone', v)} />
            <InputGroup label="Word Target" value={bookState.length} type="number" onChange={(v) => save('length', Math.max(300, parseInt(v, 10) || 300))} />
          </div>
          <button onClick={generate} disabled={loading || !bookState.title.trim()} className={`flex w-full items-center justify-center gap-2 rounded-xl py-3 font-semibold ${loading || !bookState.title.trim() ? 'cursor-not-allowed bg-[#b9b2a2] text-[#666057]' : 'bg-[#235f5f] text-[#f2f6ee] hover:bg-[#1d5151]'}`}>
            {loading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#f2f6ee] border-t-transparent" /> : <Wand2 size={16} />} Generate Blueprint
          </button>
        </div>
      </div>
      <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-6 xl:col-span-2">
        <h3 className="font-semibold">Planning Snapshot</h3>
        <div className="mt-3 space-y-2 text-sm text-[#586b6f]">
          <div>Estimated chapters: {Math.max(6, Math.min(16, Math.round(bookState.length / 3000)))}</div>
          <div>Workflow: Concept -> Outline -> Drafting -> Export</div>
          <div>Autosave enabled in browser storage.</div>
        </div>
      </div>
    </div>
  );
};

const OutlineStep: React.FC<{
  bookState: BookState;
  setBookState: SetBookState;
  onNext: () => void;
  onRun: (mode: Mode, outputs: AgentOutputs) => void;
  executeAgent: (mode: Mode, inputs: Record<string, unknown>) => Promise<AgentOutputs>;
}> = ({ bookState, setBookState, onNext, onRun, executeAgent }) => {
  const [feedback, setFeedback] = useState('');
  const [loading, setLoading] = useState(false);
  if (!bookState.outline) return <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-8 text-center">No outline yet.</div>;
  const updateTitle = (n: number, t: string) => setBookState((p) => ({ ...p, outline: { ...p.outline!, chapters: p.outline!.chapters.map((c) => (c.number === n ? { ...c, title: t } : c)) }, updatedAt: new Date().toISOString() }));
  const refine = async () => {
    if (!feedback.trim()) return toast.error('Add feedback first.');
    setLoading(true);
    try {
      const inputs = { mode: 'refine_toc', ...commonInputs(bookState), feedback: feedback.trim(), outline: bookState.outline };
      const outputs = await executeAgent('refine_toc', inputs);
      onRun('refine_toc', outputs);
      if (isSuccess(outputs) && outputs.outline) {
        setBookState((p) => ({ ...p, outline: outputs.outline || p.outline, updatedAt: new Date().toISOString() }));
        setFeedback('');
        toast.success('Outline refined.');
      } else toast.error(outputs.errors?.[0] || 'Refinement failed.');
    } catch (error) {
      toast.error(getErrorMessage(error, 'Error refining outline.'));
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 xl:grid-cols-12">
      <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-5 xl:col-span-8">
        <div className="mb-4 flex items-center justify-between"><h2 className="text-2xl font-semibold">Outline Architect</h2><button onClick={onNext} className="rounded-lg bg-[#2b665a] px-4 py-2 text-sm font-semibold text-[#f2f7ee] hover:bg-[#24574d]">Approve & Draft</button></div>
        <textarea value={bookState.outline.synopsis} onChange={(e) => setBookState((p) => ({ ...p, outline: { ...p.outline!, synopsis: e.target.value }, updatedAt: new Date().toISOString() }))} className="mb-4 h-24 w-full rounded-lg border border-[#c2b69f] bg-[#fffdf5] p-3 text-sm outline-none" />
        <div className="space-y-3">
          {bookState.outline.chapters.map((c) => (
            <div key={c.number} className="rounded-xl border border-[#c7b89f]/55 bg-[#fffdf6] p-4">
              <div className="mb-2 text-xs font-semibold uppercase text-[#587074]">Chapter {c.number}</div>
              <input value={c.title} onChange={(e) => updateTitle(c.number, e.target.value)} className="mb-2 w-full rounded-lg border border-[#c2b69f] bg-[#fffef8] px-3 py-2 text-sm outline-none" />
              <ul className="list-disc space-y-1 pl-5 text-sm text-[#607175]">{c.bullet_points.map((bp, i) => <li key={i}>{bp}</li>)}</ul>
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-5 xl:col-span-4">
        <h3 className="mb-2 font-semibold">Refinement Assistant</h3>
        <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="e.g. add more practical examples in middle chapters." className="h-36 w-full rounded-lg border border-[#c2b69f] bg-[#fffef8] p-3 text-sm outline-none" />
        <button onClick={refine} disabled={loading || !feedback.trim()} className={`mt-3 flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold ${loading || !feedback.trim() ? 'cursor-not-allowed bg-[#b9b2a2] text-[#666057]' : 'bg-[#2f6767] text-[#f2f6ee] hover:bg-[#285858]'}`}>{loading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#f2f6ee] border-t-transparent" /> : <Wand2 size={15} />} Refine Outline</button>
      </div>
    </div>
  );
};

const DraftingStep: React.FC<{
  bookState: BookState;
  setBookState: SetBookState;
  onNext: () => void;
  onRun: (mode: Mode, outputs: AgentOutputs) => void;
  executeAgent: (mode: Mode, inputs: Record<string, unknown>) => Promise<AgentOutputs>;
}> = ({ bookState, setBookState, onNext, onRun, executeAgent }) => {
  const [loading, setLoading] = useState(false);
  useEffect(() => { if (!bookState.currentChapterId && bookState.outline?.chapters[0]) setBookState((p) => ({ ...p, currentChapterId: p.outline!.chapters[0].number, updatedAt: new Date().toISOString() })); }, [bookState.currentChapterId, bookState.outline, setBookState]);
  if (!bookState.outline) return <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-8 text-center">No outline available.</div>;
  const current = bookState.outline.chapters.find((c) => c.number === bookState.currentChapterId) || null;
  const content = current ? bookState.chaptersContent[current.number] || '' : '';
  const gen = async (n: number) => {
    setLoading(true);
    try {
      const inputs = { mode: 'chapter', ...commonInputs(bookState), outline: bookState.outline, chapter_number: n };
      const outputs = await executeAgent('chapter', inputs);
      onRun('chapter', outputs);
      if (isSuccess(outputs) && outputs.chapter?.content) {
        setBookState((p) => ({ ...p, chaptersContent: { ...p.chaptersContent, [n]: outputs.chapter?.content || '' }, currentChapterId: n, updatedAt: new Date().toISOString() }));
        toast.success(`Chapter ${n} generated.`);
      } else toast.error(outputs.errors?.[0] || 'Chapter generation failed.');
    } catch (error) {
      toast.error(getErrorMessage(error, 'Error generating chapter.'));
    } finally { setLoading(false); }
  };
  const copy = async () => { if (!content.trim()) return toast.error('No content to copy.'); try { await navigator.clipboard.writeText(content); toast.success('Copied to clipboard.'); } catch { toast.error('Clipboard failed.'); } };
  const dl = () => { if (!current || !content.trim()) return toast.error('No content to download.'); const b = new Blob([content], { type: 'text/plain;charset=utf-8' }); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = `${bookState.title || 'book'}_chapter_${current.number}.txt`; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(u); };
  const totalWords = Object.values(bookState.chaptersContent).reduce((s, t) => s + words(t), 0);
  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
      <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 xl:col-span-3"><div className="border-b border-[#cfbf9f]/55 p-4 font-semibold">Chapters</div><div className="max-h-[56vh] space-y-1 overflow-y-auto p-2">{bookState.outline.chapters.map((c) => <button key={c.number} onClick={() => setBookState((p) => ({ ...p, currentChapterId: c.number, updatedAt: new Date().toISOString() }))} className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm ${bookState.currentChapterId === c.number ? 'border border-[#2f6767]/45 bg-[#e8f0ea]' : 'hover:bg-[#f3ecdd]'}`}><span className="truncate">{c.number}. {c.title}</span><span className={`h-2.5 w-2.5 rounded-full ${bookState.chaptersContent[c.number]?.trim() ? 'bg-[#2f8568]' : 'bg-[#b1a48a]'}`} /></button>)}</div></div>
      <div className="relative flex flex-col overflow-hidden rounded-2xl border border-[#baa98c]/50 bg-[#fffdf4] xl:col-span-6">
        <div className="flex items-center justify-between border-b border-[#cfbf9f]/55 bg-[#faf2df] p-3"><div><div className="text-sm font-semibold">{current?.title || 'Select chapter'}</div><div className="text-xs text-[#69787b]">{words(content)} words in chapter | {totalWords} total</div></div><div className="flex gap-2"><button onClick={() => toast.success('Saved locally.')} className="rounded-md border border-[#c2b396] bg-[#fff7e5] p-2"><Save size={14} /></button><button onClick={copy} className="rounded-md border border-[#c2b396] bg-[#fff7e5] p-2"><FileText size={14} /></button><button onClick={dl} className="rounded-md border border-[#c2b396] bg-[#fff7e5] p-2"><Download size={14} /></button></div></div>
        {loading && <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#faf4e5]/90"><span className="h-7 w-7 animate-spin rounded-full border-2 border-[#2f6767] border-t-transparent" /></div>}
        <textarea value={content} onChange={(e) => current && setBookState((p) => ({ ...p, chaptersContent: { ...p.chaptersContent, [current.number]: e.target.value }, updatedAt: new Date().toISOString() }))} className="h-[56vh] w-full resize-none border-none bg-transparent p-6 text-[15px] leading-relaxed outline-none" placeholder="Generate chapter then edit manually." />
      </div>
      <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-4 xl:col-span-3"><div className="mb-3 text-sm font-semibold uppercase text-[#50676b]">Draft Controls</div><button onClick={() => current && gen(current.number)} disabled={loading || !current} className={`mb-2 flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-semibold ${loading || !current ? 'cursor-not-allowed bg-[#b9b2a2] text-[#666057]' : 'bg-[#2f6767] text-[#f2f6ee] hover:bg-[#285858]'}`}><Wand2 size={15} /> {content.trim() ? 'Regenerate' : 'Generate'} Current</button><button onClick={onNext} className="w-full rounded-lg bg-[#314f5c] py-2.5 text-sm font-semibold text-[#edf3ef] hover:bg-[#29424e]">Go To Export</button>{current && <div className="mt-4 rounded-lg border border-[#c7b79a]/60 bg-[#fbf4e3] p-3"><div className="mb-1 text-xs font-semibold uppercase text-[#55696d]">Chapter Goal</div><ul className="list-disc space-y-1 pl-4 text-xs text-[#637478]">{current.bullet_points.map((bp, i) => <li key={i}>{bp}</li>)}</ul></div>}</div>
    </div>
  );
};

const ExportStep: React.FC<{
  bookState: BookState;
  onRun: (mode: Mode, outputs: AgentOutputs) => void;
  executeAgent: (mode: Mode, inputs: Record<string, unknown>) => Promise<AgentOutputs>;
}> = ({ bookState, onRun, executeAgent }) => {
  const [loading, setLoading] = useState(false);
  const outline = bookState.outline;
  const missing = (outline?.chapters || []).filter((c) => !bookState.chaptersContent[c.number]?.trim());
  const doExport = async (format: 'pdf' | 'docx' | 'both') => {
    if (!outline) return toast.error('No outline available.');
    setLoading(true);
    const id = toast.loading(`Exporting ${format.toUpperCase()}...`);
    try {
      const chapters = outline.chapters.map((c) => ({ number: c.number, title: c.title, content: bookState.chaptersContent[c.number] || '(Chapter not written)' }));
      const inputs = { mode: 'export', ...commonInputs(bookState), outline, chapters, export_format: format };
      const outputs = await executeAgent('export', inputs);
      onRun('export', outputs);
      if (!isSuccess(outputs)) return toast.error(outputs.errors?.[0] || 'Export failed.', { id });
      if ((format === 'pdf' || format === 'both') && outputs.pdf_base64) downloadBase64(outputs.pdf_base64, outputs.pdf_filename || `${bookState.title || 'book'}.pdf`, 'application/pdf');
      if ((format === 'docx' || format === 'both') && outputs.docx_base64) downloadBase64(outputs.docx_base64, outputs.docx_filename || `${bookState.title || 'book'}.docx`, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
      toast.success('Export complete.', { id });
    } catch (error) {
      toast.error(getErrorMessage(error, 'Export request failed.'), { id });
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 xl:grid-cols-5">
      <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-6 xl:col-span-3">
        <h2 className="mb-2 text-2xl font-semibold">Publishing Desk</h2>
        <p className="mb-4 text-sm text-[#5e7073]">{missing.length ? `${missing.length} chapters are incomplete; placeholders will be used.` : 'All chapters contain content.'}</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <button onClick={() => doExport('pdf')} disabled={loading} className={`rounded-xl py-3 text-sm font-semibold ${loading ? 'cursor-not-allowed bg-[#bcb3a4] text-[#6d665a]' : 'bg-[#9b3b39] text-[#fff6f4] hover:bg-[#812f2d]'}`}>Export PDF</button>
          <button onClick={() => doExport('docx')} disabled={loading} className={`rounded-xl py-3 text-sm font-semibold ${loading ? 'cursor-not-allowed bg-[#bcb3a4] text-[#6d665a]' : 'bg-[#2c5e90] text-[#f3f7ff] hover:bg-[#244e77]'}`}>Export DOCX</button>
          <button onClick={() => doExport('both')} disabled={loading} className={`rounded-xl py-3 text-sm font-semibold ${loading ? 'cursor-not-allowed bg-[#bcb3a4] text-[#6d665a]' : 'bg-[#2f6767] text-[#f2f7ed] hover:bg-[#275959]'}`}>Export Both</button>
        </div>
      </div>
      <div className="rounded-2xl border border-[#baa98c]/50 bg-[#fff8ea]/85 p-6 xl:col-span-2">
        <h3 className="mb-2 font-semibold">Export Audit</h3>
        {missing.length ? <ul className="list-disc space-y-1 pl-5 text-sm text-[#637376]">{missing.map((c) => <li key={c.number}>{c.number}. {c.title}</li>)}</ul> : <p className="text-sm text-[#607277]">No missing chapters.</p>}
      </div>
    </div>
  );
};

const InputGroup: React.FC<{ label: string; value: string | number; onChange: (v: string) => void; type?: 'text' | 'number'; placeholder?: string }> = ({ label, value, onChange, type = 'text', placeholder }) => (
  <div>
    <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-[#66777b]">{label}</label>
    <input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="w-full rounded-xl border border-[#c7bca5] bg-[#fffdf5] px-4 py-2.5 outline-none focus:border-[#2f6767]" />
  </div>
);

export default BookWritingAgentPage;
