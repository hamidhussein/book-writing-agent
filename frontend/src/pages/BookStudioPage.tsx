import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Book, List, Download, Save, Edit3, Wand2, ChevronRight, ChevronLeft, FileText, CheckCircle2 } from 'lucide-react';
import { Toaster, toast } from 'react-hot-toast';

import { api as axiosInstance } from '../api/client';

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
  used_fallback?: boolean;
  fallback_stages?: string[];
  progress?: {
    current_node?: string;
    revision_count?: number;
    node_status?: Record<string, string>;
    completed_nodes?: string[];
  };
  outline?: OutlineData;
  chapter?: { number: number; title: string; content: string; summary?: string };
  metadata?: Record<string, unknown>;
  next_steps?: string[];
  timings_ms?: {
    total_ms?: number;
    nodes?: Record<string, number>;
  };
  pdf_base64?: string;
  pdf_filename?: string;
  docx_base64?: string;
  docx_filename?: string;
  assistant_response?: AssistantResponse;
}

type SourcePriority = 'primary' | 'supporting' | 'tone-only';
type AssistantRole = 'assistant' | 'user';

interface AssistantMessage {
  role: AssistantRole;
  content: string;
}

interface AssistantResponse {
  assistant_reply: string;
  field_updates: Record<string, unknown>;
  next_field?: string;
  is_finalized?: boolean;
  missing_required?: string[];
  suggestions?: string[];
}

interface AssistantQuickChoice {
  label: string;
  message: string;
}

interface BookState {
  title: string;
  subtitle: string;
  genre: string;
  audience: string;
  audienceKnowledgeLevel: string;
  culturalContext: string;
  bookPurpose: string;
  primaryCta: string;
  language: string;
  tone: string;
  writingStyle: string;
  pointOfView: string;
  tense: string;
  sentenceRhythm: string;
  vocabularyLevel: string;
  ghostwritingMode: boolean;
  booksToEmulate: string;
  styleReferencePassage: string;
  customInstructions: string;
  pageFeel: string;
  publishingIntent: string;
  chapterLength: string;
  frontMatter: string[];
  backMatter: string[];
  richElements: string[];
  contentBoundaries: string;
  length: number;
  outline: OutlineData | null;
  currentChapterId: number | null;
  chaptersContent: Record<number, string>;
  chapterReviewTelemetry: Record<number, ChapterReviewTelemetry>;
  backendProjectId: string | null;
  backendMetadata: Record<string, unknown>;
  updatedAt: string;
  assistantMessages: AssistantMessage[];
  assistantDraft: Partial<BookState>;
  assistantNextField: string;
  assistantMissing: string[];
  assistantReadyToFinalize: boolean;
  assistantSuggestions: string[];
  assistantLastAppliedFields: string[];
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
  metadata_json?: Record<string, unknown>;
}

interface BackendChapter {
  id: string;
  project: string;
  number: number;
  title: string;
  content: string;
  status?: string;
}

interface SourceDocument {
  id: string;
  project: string;
  title: string;
  source_type: string;
  content: string;
  metadata_json?: Record<string, unknown>;
  index_stats?: {
    chunks_total?: number;
    chunks_indexed?: number;
  };
}

interface AgentRunRecord {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  mode: Mode;
  output_payload?: AgentOutputs;
  error_message?: string;
  trace_id?: string;
}

interface RunProgressSnapshot {
  label: string;
  revisionCount: number | null;
}

interface ChapterReviewTelemetry {
  score: number | null;
  explicitShouldRevise: boolean;
  effectiveShouldRevise: boolean;
  revisionCount: number | null;
  issues: string[];
  critique: string;
  wordCount: number | null;
  minimumWordCount: number | null;
  guardrailFail: boolean;
  profileComplianceFail: boolean;
  profileComplianceIssues: string[];
  fallbackStages: string[];
  usedFallback: boolean;
  runMs: number | null;
  generatedAt: string;
}

type SetBookState = React.Dispatch<React.SetStateAction<BookState>>;

const AGENT_ID = 'eef314c9-183b-4d87-9d6c-88815a72be15';
const STORAGE_KEY = 'book_agent_ui_state_v3';

const DEFAULT_STATE: BookState = {
  title: '',
  subtitle: '',
  genre: 'Non-fiction',
  audience: 'General readers',
  audienceKnowledgeLevel: 'Complete Beginner',
  culturalContext: '',
  bookPurpose: 'Teach a Skill',
  primaryCta: '',
  language: 'English',
  tone: 'Informative',
  writingStyle: 'Instructional',
  pointOfView: 'Second Person',
  tense: 'Timeless / As Appropriate',
  sentenceRhythm: 'Mixed',
  vocabularyLevel: 'Intermediate',
  ghostwritingMode: false,
  booksToEmulate: '',
  styleReferencePassage: '',
  customInstructions: '',
  pageFeel: 'Standard',
  publishingIntent: 'Self-publish',
  chapterLength: 'Medium ~3000w',
  frontMatter: ['Introduction'],
  backMatter: [],
  richElements: ['Lists'],
  contentBoundaries: '',
  length: 3000,
  outline: null,
  currentChapterId: null,
  chaptersContent: {},
  chapterReviewTelemetry: {},
  backendProjectId: null,
  backendMetadata: {},
  updatedAt: new Date().toISOString(),
  assistantMessages: [
    {
      role: 'assistant',
      content:
        "Hi! I'm your Book Studio Assistant. I'm here to help you turn your idea into a complete production brief. To get started, what's your book about, or what's the title you have in mind?",
    },
  ],
  assistantDraft: {},
  assistantNextField: '',
  assistantMissing: [],
  assistantReadyToFinalize: false,
  assistantSuggestions: [],
  assistantLastAppliedFields: [],
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
      chapterReviewTelemetry: (parsed.chapterReviewTelemetry && typeof parsed.chapterReviewTelemetry === 'object')
        ? parsed.chapterReviewTelemetry as Record<number, ChapterReviewTelemetry>
        : {},
      backendProjectId: parsed.backendProjectId || null,
      backendMetadata: (parsed.backendMetadata && typeof parsed.backendMetadata === 'object') ? parsed.backendMetadata : {},
      frontMatter: Array.isArray(parsed.frontMatter) ? parsed.frontMatter : DEFAULT_STATE.frontMatter,
      backMatter: Array.isArray(parsed.backMatter) ? parsed.backMatter : DEFAULT_STATE.backMatter,
      richElements: Array.isArray(parsed.richElements) ? parsed.richElements : DEFAULT_STATE.richElements,
      assistantMessages: Array.isArray(parsed.assistantMessages) && parsed.assistantMessages.length > 0 ? parsed.assistantMessages : DEFAULT_STATE.assistantMessages,
      assistantDraft: (parsed.assistantDraft && typeof parsed.assistantDraft === 'object') ? parsed.assistantDraft : {},
      assistantNextField: typeof parsed.assistantNextField === 'string' ? parsed.assistantNextField : 'title',
      assistantMissing: Array.isArray(parsed.assistantMissing) ? parsed.assistantMissing : [],
      assistantReadyToFinalize: !!parsed.assistantReadyToFinalize,
      assistantLastAppliedFields: Array.isArray(parsed.assistantLastAppliedFields) ? parsed.assistantLastAppliedFields.map((v) => String(v)) : [],
    };
  } catch {
    return DEFAULT_STATE;
  }
};

const words = (text: string) => (text.trim() ? text.trim().split(/\s+/).length : 0);
const isSuccess = (o: AgentOutputs) => (o.status ? o.status === 'success' : Boolean(o.outline || o.chapter || o.pdf_base64 || o.docx_base64));
const PROFILE_REQUIRED_FIELDS: Array<keyof BookState> = [
  'title',
  'genre',
  'language',
  'length',
  'publishingIntent',
  'audience',
  'audienceKnowledgeLevel',
  'bookPurpose',
  'tone',
  'writingStyle',
  'pointOfView',
  'sentenceRhythm',
  'vocabularyLevel',
  'chapterLength',
];
const PROFILE_LABELS: Record<string, string> = {
  title: 'Book Title',
  genre: 'Genre',
  language: 'Language',
  length: 'Target Word Count',
  publishingIntent: 'Publishing Intent',
  audience: 'Target Audience',
  audienceKnowledgeLevel: 'Audience Knowledge Level',
  bookPurpose: 'Book Purpose',
  tone: 'Tone',
  writingStyle: 'Writing Style',
  pointOfView: 'Point of View',
  tense: 'Tense',
  sentenceRhythm: 'Sentence Rhythm',
  vocabularyLevel: 'Vocabulary Level',
  chapterLength: 'Chapter Length',
};

const buildProfilePayload = (s: BookState) => ({
  title: s.title,
  subtitle: s.subtitle,
  genre: s.genre,
  language: s.language,
  length: s.length,
  pageFeel: s.pageFeel,
  publishingIntent: s.publishingIntent,
  audience: s.audience,
  audienceKnowledgeLevel: s.audienceKnowledgeLevel,
  culturalContext: s.culturalContext,
  bookPurpose: s.bookPurpose,
  primaryCta: s.primaryCta,
  tone: s.tone,
  writingStyle: s.writingStyle,
  pointOfView: s.pointOfView,
  tense: s.tense,
  sentenceRhythm: s.sentenceRhythm,
  vocabularyLevel: s.vocabularyLevel,
  ghostwritingMode: s.ghostwritingMode,
  booksToEmulate: s.booksToEmulate,
  styleReferencePassage: s.styleReferencePassage,
  customInstructions: s.customInstructions,
  chapterLength: s.chapterLength,
  frontMatter: s.frontMatter,
  backMatter: s.backMatter,
  richElements: s.richElements,
  contentBoundaries: s.contentBoundaries,
});

const profileMissing = (s: BookState) =>
  PROFILE_REQUIRED_FIELDS.filter((key) => {
    const value = s[key];
    if (typeof value === 'string') return !value.trim();
    if (typeof value === 'number') return value <= 0;
    if (Array.isArray(value)) return value.length === 0;
    return value === null || value === undefined;
  });

const profileMissingFromPayload = (profile: Record<string, unknown>) =>
  PROFILE_REQUIRED_FIELDS.filter((key) => {
    const value = profile[String(key)];
    if (typeof value === 'string') return !value.trim();
    if (typeof value === 'number') return value <= 0;
    if (Array.isArray(value)) return value.length === 0;
    return value === null || value === undefined;
  });

const hasProfileStarted = (s: BookState) => {
  const normalized = (value: string[]) => value.join('|');
  return (
    Boolean(s.title.trim()) ||
    Boolean(s.subtitle.trim()) ||
    Boolean(s.customInstructions.trim()) ||
    Boolean(s.styleReferencePassage.trim()) ||
    Boolean(s.booksToEmulate.trim()) ||
    Boolean(s.contentBoundaries.trim()) ||
    Boolean(s.culturalContext.trim()) ||
    Boolean(s.primaryCta.trim()) ||
    s.genre !== DEFAULT_STATE.genre ||
    s.audience !== DEFAULT_STATE.audience ||
    s.audienceKnowledgeLevel !== DEFAULT_STATE.audienceKnowledgeLevel ||
    s.bookPurpose !== DEFAULT_STATE.bookPurpose ||
    s.language !== DEFAULT_STATE.language ||
    s.tone !== DEFAULT_STATE.tone ||
    s.writingStyle !== DEFAULT_STATE.writingStyle ||
    s.pointOfView !== DEFAULT_STATE.pointOfView ||
    s.tense !== DEFAULT_STATE.tense ||
    s.sentenceRhythm !== DEFAULT_STATE.sentenceRhythm ||
    s.vocabularyLevel !== DEFAULT_STATE.vocabularyLevel ||
    s.pageFeel !== DEFAULT_STATE.pageFeel ||
    s.publishingIntent !== DEFAULT_STATE.publishingIntent ||
    s.chapterLength !== DEFAULT_STATE.chapterLength ||
    s.length !== DEFAULT_STATE.length ||
    s.ghostwritingMode !== DEFAULT_STATE.ghostwritingMode ||
    normalized(s.frontMatter) !== normalized(DEFAULT_STATE.frontMatter) ||
    normalized(s.backMatter) !== normalized(DEFAULT_STATE.backMatter) ||
    normalized(s.richElements) !== normalized(DEFAULT_STATE.richElements)
  );
};

const profileCompleteness = (s: BookState) => {
  if (!hasProfileStarted(s)) {
    return 0;
  }
  const missing = profileMissing(s);
  const complete = PROFILE_REQUIRED_FIELDS.length - missing.length;
  return Math.round((complete / PROFILE_REQUIRED_FIELDS.length) * 100);
};

const profileInstructionBrief = (s: BookState) => {
  const profile = buildProfilePayload(s);
  return [
    `Title: ${s.title || 'Untitled'}`,
    s.subtitle.trim() ? `Subtitle: ${s.subtitle}` : '',
    `Genre: ${s.genre}`,
    `Audience: ${s.audience}`,
    `Knowledge level: ${s.audienceKnowledgeLevel}`,
    `Purpose: ${s.bookPurpose}`,
    `Tone/Style: ${s.tone} | ${s.writingStyle}`,
    `POV/Tense/Rhythm/Vocab: ${s.pointOfView} | ${s.tense} | ${s.sentenceRhythm} | ${s.vocabularyLevel}`,
    s.ghostwritingMode ? 'Ghostwriting mode: ON' : 'Ghostwriting mode: OFF',
    s.booksToEmulate.trim() ? `Books to emulate: ${s.booksToEmulate}` : '',
    s.customInstructions.trim() ? `Custom instructions: ${s.customInstructions}` : '',
    s.contentBoundaries.trim() ? `Content boundaries: ${s.contentBoundaries}` : '',
    `Structure: ${s.chapterLength}; Front matter: ${s.frontMatter.join(', ') || 'None'}; Back matter: ${s.backMatter.join(', ') || 'None'}; Rich elements: ${s.richElements.join(', ') || 'None'}`,
    `Profile JSON: ${JSON.stringify(profile)}`,
  ]
    .filter(Boolean)
    .join('\n');
};

const commonInputs = (s: BookState) => ({
  book_title: s.title,
  subtitle: s.subtitle,
  genre: s.genre,
  target_audience: s.audience,
  audience_knowledge_level: s.audienceKnowledgeLevel,
  cultural_context: s.culturalContext,
  book_purpose: s.bookPurpose,
  primary_cta: s.primaryCta,
  language: s.language,
  tone: s.tone,
  writing_style: s.writingStyle,
  point_of_view: s.pointOfView,
  writing_tense: s.tense,
  tense: s.tense,
  sentence_rhythm: s.sentenceRhythm,
  vocabulary_level: s.vocabularyLevel,
  ghostwriting_mode: s.ghostwritingMode,
  books_to_emulate: s.booksToEmulate,
  style_reference_passage: s.styleReferencePassage,
  custom_instructions: s.customInstructions,
  chapter_length: s.chapterLength,
  front_matter: s.frontMatter,
  back_matter: s.backMatter,
  rich_elements: s.richElements,
  content_boundaries: s.contentBoundaries,
  page_feel: s.pageFeel,
  publishing_intent: s.publishingIntent,
  book_length: s.length,
  profile: buildProfilePayload(s),
  instruction_brief: profileInstructionBrief(s),
});

const API_PATHS = {
  projectCreate: ['/books/projects/'],
  projectDetail: (projectId: string) => [`/books/projects/${projectId}/`],
  projectChapters: (projectId: string) => [`/books/projects/${projectId}/chapters/`],
  projectSources: (projectId: string) => [`/books/projects/${projectId}/sources/`],
  projectKnowledgeUpload: (projectId: string) => [`/books/projects/${projectId}/knowledge-upload/`],
  projectProfileAssistant: (projectId: string) => [`/books/projects/${projectId}/profile-assistant/`],
  chapterList: ['/books/chapters/'],
  chapterDetail: (chapterId: string) => [`/books/chapters/${chapterId}/`],
  runCreate: ['/agents/runs/'],
  runDetail: (runId: string) => [`/agents/runs/${runId}/`],
  legacyExecute: [`/agents/${AGENT_ID}/execute`],
};

const STEP_TITLES = [
  'Book Identity',
  'Audience & Purpose',
  'Voice & Style',
  'Structure Preferences',
  'Knowledge Base',
] as const;

const STEP_NOTES = [
  'Define the core identity for the book before any generation starts.',
  'Set reader context so depth and framing match your target audience.',
  'Lock tone, narrative style, and voice consistency across chapters.',
  'Control chapter structure, supporting elements, and boundaries.',
  'Add trusted source material for grounding and retrieval.',
] as const;

const GENRE_OPTIONS = ['Non-fiction', 'Fiction', 'Business', 'Education', 'Technology', 'Self-help', 'Memoir', 'Academic'];
const LANGUAGE_OPTIONS = ['English', 'Hindi', 'Urdu', 'Spanish', 'French', 'German', 'Arabic'];
const PAGE_FEEL_OPTIONS = ['Pocket Guide', 'Standard', 'Comprehensive Reference'];
const PUBLISHING_INTENT_OPTIONS = ['Self-publish', 'Traditional', 'Corporate/Internal', 'Academic'];
const KNOWLEDGE_LEVEL_OPTIONS = ['Complete Beginner', 'Intermediate', 'Expert'];
const PURPOSE_OPTIONS = ['Establish Authority', 'Teach a Skill', 'Tell a Story', 'Sell a Service', 'Document Research'];
const TONE_OPTIONS = ['Formal', 'Conversational', 'Inspirational', 'Academic', 'Humorous', 'Dark', 'Neutral', 'Informative'];
const WRITING_STYLE_OPTIONS = ['Narrative', 'Analytical', 'Instructional', 'Lyrical', 'Journalistic'];
const POV_OPTIONS = ['First Person', 'Second Person', 'Third Person', 'Omniscient'];
const TENSE_OPTIONS = ['Timeless / As Appropriate', 'Present', 'Past'];
const RHYTHM_OPTIONS = ['Short & Punchy', 'Long & Flowing', 'Mixed'];
const VOCAB_OPTIONS = ['Simple', 'Intermediate', 'Technical', 'Literary'];
const CHAPTER_LENGTH_OPTIONS = ['Short ~1500w', 'Medium ~3000w', 'Long ~5000w'];
const CHAPTER_LENGTH_WORDS: Record<string, number> = {
  'Short ~1500w': 1500,
  'Medium ~3000w': 3000,
  'Long ~5000w': 5000,
};
const FRONT_MATTER_OPTIONS = ['Foreword', 'Preface', 'Introduction'];
const BACK_MATTER_OPTIONS = ['Glossary', 'Appendix', 'Bibliography', 'About the Author'];
const RICH_ELEMENT_OPTIONS = ['Tables', 'Flowcharts', 'Figures & Diagrams', 'Callout Boxes', 'Code Blocks', 'Quotes', 'Lists'];

const ASSISTANT_FIELD_LABELS: Record<string, string> = {
  ...PROFILE_LABELS,
  subtitle: 'Subtitle',
  pageFeel: 'Page Feel',
  primaryCta: 'Primary CTA',
  culturalContext: 'Cultural Context',
  ghostwritingMode: 'Author Voice Mode',
  tense: 'Tense',
  customInstructions: 'Topics / Skills',
  booksToEmulate: 'Reference Books',
  styleReferencePassage: 'Style Reference Passage',
  frontMatter: 'Front Matter',
  backMatter: 'Back Matter',
  richElements: 'Rich Elements',
  contentBoundaries: 'Content Boundaries',
};

const quickChoice = (label: string, message?: string): AssistantQuickChoice => ({
  label,
  message: message || label,
});

const ASSISTANT_MULTI_SELECT_FIELDS = new Set(['frontMatter', 'backMatter', 'richElements']);

const isAssistantMultiSelectField = (field: string): boolean => ASSISTANT_MULTI_SELECT_FIELDS.has(field);

const buildAssistantMultiSelectMessage = (
  field: string,
  selectedChoices: AssistantQuickChoice[],
): string => {
  const labels = selectedChoices.map((choice) => choice.label);
  if (!labels.length) {
    return '';
  }
  if (field === 'frontMatter') {
    return `Include these front matter items: ${labels.join(', ')}`;
  }
  if (field === 'backMatter') {
    return `Include these back matter items: ${labels.join(', ')}`;
  }
  if (field === 'richElements') {
    return `Use these rich elements: ${labels.join(', ')}`;
  }
  return labels.join(', ');
};

const quickChoicesForField = (
  field: string,
  readyToFinalize: boolean,
): AssistantQuickChoice[] => {
  switch (field) {
    case 'frontMatter':
      return FRONT_MATTER_OPTIONS.map((option) => quickChoice(option));
    case 'backMatter':
      return BACK_MATTER_OPTIONS.map((option) => quickChoice(option));
    case 'richElements':
      return RICH_ELEMENT_OPTIONS.map((option) => quickChoice(option));
    default:
      if (readyToFinalize) {
        return [quickChoice('Finalize brief', 'yes finalize')];
      }
      return [];
  }
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const RUN_TIMEOUT_DEFAULT_MS = 240_000;
const RUN_TIMEOUT_CHAPTER_MS = 480_000;
const FORCE_SYNC_RUNS = (import.meta.env.VITE_FORCE_SYNC_RUNS ?? '1') !== '0';

const NODE_LABELS: Record<string, string> = {
  run_toc: 'Outline generation',
  run_refine_toc: 'Outline refinement',
  run_chapter: 'Chapter pipeline',
  run_export: 'Export generation',
  chapter_retrieve_context: 'Retrieve context',
  chapter_plan: 'Plan chapter',
  chapter_draft: 'Draft chapter',
  chapter_review: 'Review chapter',
  chapter_persist: 'Persist chapter',
};

const toRecord = (value: unknown): Record<string, unknown> =>
  (value && typeof value === 'object') ? (value as Record<string, unknown>) : {};

const normalizeMetadata = (value: unknown): Record<string, unknown> => toRecord(value);

const extractLlmRuntime = (metadata: Record<string, unknown>): Record<string, unknown> => {
  const llmRuntime = metadata.llm_runtime;
  return toRecord(llmRuntime);
};

const nodeLabelFromKey = (nodeKey: string): string => {
  const key = nodeKey.trim();
  if (!key) {
    return 'Running';
  }
  return NODE_LABELS[key] || key.replaceAll('_', ' ');
};

const extractRunProgress = (source: AgentRunRecord | AgentOutputs | null | undefined): RunProgressSnapshot | null => {
  if (!source || typeof source !== 'object') {
    return null;
  }

  const payloadValue = ('output_payload' in source)
    ? source.output_payload
    : source;
  const payload = toRecord(payloadValue);
  if (!Object.keys(payload).length) {
    return null;
  }

  const progress = toRecord(payload.progress);
  if (!Object.keys(progress).length) {
    return null;
  }

  const nodeKey = typeof progress.current_node === 'string' ? progress.current_node.trim() : '';
  const revisionCount = typeof progress.revision_count === 'number' && Number.isFinite(progress.revision_count)
    ? Math.max(0, Math.floor(progress.revision_count))
    : null;
  return {
    label: nodeLabelFromKey(nodeKey),
    revisionCount,
  };
};

const extractChapterReviewTelemetry = (outputs: AgentOutputs): ChapterReviewTelemetry | null => {
  const metadata = toRecord(outputs.metadata);
  const review = toRecord(metadata.review);
  if (!Object.keys(review).length) {
    return null;
  }

  const asInt = (value: unknown): number | null => {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return Math.trunc(value);
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
  };

  const issues = Array.isArray(review.issues)
    ? review.issues.map((item) => String(item).trim()).filter(Boolean)
    : [];
  const profileComplianceIssues = Array.isArray(review.profile_compliance_issues)
    ? review.profile_compliance_issues.map((item) => String(item).trim()).filter(Boolean)
    : [];
  const fallbackStages = Array.isArray(outputs.fallback_stages)
    ? outputs.fallback_stages.map((item) => String(item).trim()).filter(Boolean)
    : [];

  const timings = toRecord(outputs.timings_ms);
  const timingNodes = toRecord(timings.nodes);

  return {
    score: asInt(review.score),
    explicitShouldRevise: Boolean(review.should_revise),
    effectiveShouldRevise: Boolean(review.effective_should_revise),
    revisionCount: asInt(outputs.progress?.revision_count),
    issues,
    critique: typeof review.critique === 'string' ? review.critique.trim() : '',
    wordCount: asInt(review.word_count),
    minimumWordCount: asInt(review.minimum_word_count),
    guardrailFail: Boolean(review.guardrail_fail),
    profileComplianceFail: Boolean(review.profile_compliance_fail),
    profileComplianceIssues,
    fallbackStages,
    usedFallback: Boolean(outputs.used_fallback),
    runMs: asInt(timingNodes.run_chapter_ms ?? timings.total_ms),
    generatedAt: new Date().toISOString(),
  };
};

const formatFallbackStages = (stages: string[] | undefined): string => {
  if (!Array.isArray(stages) || stages.length === 0) {
    return 'fallback';
  }
  const formatted = stages.map((stage) => nodeLabelFromKey(String(stage)));
  return formatted.join(', ');
};

async function requestWithFallback<T>(
  method: 'get' | 'post' | 'patch' | 'delete',
  paths: string[],
  config: { data?: unknown; params?: Record<string, unknown>; timeoutMs?: number } = {}
): Promise<T> {
  let lastError: unknown;
  for (const path of paths) {
    try {
      const response = await axiosInstance.request<T>({
        method,
        url: path,
        data: config.data,
        params: config.params,
        timeout: config.timeoutMs,
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
  const normalizedTitle = state.title.trim() || 'Untitled Project';
  const profile = buildProfilePayload(state);
  const instructionBrief = profileInstructionBrief(state);
  const persistedMetadata = normalizeMetadata(state.backendMetadata);
  const llmRuntime = extractLlmRuntime(persistedMetadata);
  const metadataJson = {
    user_concept: {
      profile,
      subtitle: state.subtitle,
      instruction_brief: instructionBrief,
    },
    llm_runtime: llmRuntime,
    // Backward-compat root mirrors for legacy readers.
    profile,
    subtitle: state.subtitle,
    instruction_brief: instructionBrief,
  };

  const payload = {
    title: normalizedTitle,
    genre: state.genre,
    target_audience: state.audience,
    language: state.language,
    tone: state.tone,
    target_word_count: state.length,
    outline_json: state.outline || {},
    metadata_json: metadataJson,
  };

  if (state.backendProjectId) {
    try {
      const project = await requestWithFallback<BackendProject>('patch', API_PATHS.projectDetail(state.backendProjectId), { data: payload });
      setState((prev) => {
        const nextMetadata = normalizeMetadata(project.metadata_json);
        return {
          ...prev,
          backendProjectId: project.id || prev.backendProjectId,
          backendMetadata: Object.keys(nextMetadata).length ? nextMetadata : prev.backendMetadata,
          updatedAt: new Date().toISOString(),
        };
      });
      return project.id || state.backendProjectId;
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      if (status !== 404) {
        throw error;
      }
      // Stale local project pointer: clear and recreate automatically.
      setState((prev) => ({
        ...prev,
        backendProjectId: null,
        backendMetadata: {},
        updatedAt: new Date().toISOString(),
      }));
    }
  }

  const created = await requestWithFallback<BackendProject>('post', API_PATHS.projectCreate, { data: payload });
  if (!created?.id) {
    throw new Error('Failed to create backend project.');
  }

  setState((prev) => ({
    ...prev,
    backendProjectId: created.id,
    backendMetadata: normalizeMetadata(created.metadata_json),
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

async function runViaAsyncApi(
  mode: Mode,
  state: BookState,
  setState: SetBookState,
  inputs: Record<string, unknown>,
  onProgress?: (snapshot: RunProgressSnapshot | null) => void,
): Promise<AgentOutputs> {
  const projectId = await ensureProject(state, setState);
  if (mode === 'export') {
    await syncChapters(projectId, state);
  }

  const run = await requestWithFallback<AgentRunRecord>('post', API_PATHS.runCreate, {
    data: { project_id: projectId, mode, inputs },
    params: FORCE_SYNC_RUNS ? { sync: 1 } : undefined,
    timeoutMs: FORCE_SYNC_RUNS
      ? (mode === 'chapter' ? RUN_TIMEOUT_CHAPTER_MS : RUN_TIMEOUT_DEFAULT_MS) + 60_000
      : undefined,
  });
  if (!run?.id) {
    throw new Error('Run creation failed.');
  }

  let currentRun = run;
  const timeoutMs = mode === 'chapter' ? RUN_TIMEOUT_CHAPTER_MS : RUN_TIMEOUT_DEFAULT_MS;
  onProgress?.({ label: 'Queued', revisionCount: null });
  const started = Date.now();
  while (currentRun.status === 'queued' || currentRun.status === 'running') {
    if (Date.now() - started > timeoutMs) {
      throw new Error('Run timed out. Please retry.');
    }
    await sleep(1200);
    currentRun = await requestWithFallback<AgentRunRecord>('get', API_PATHS.runDetail(run.id));
    const progress = extractRunProgress(currentRun);
    if (progress) {
      onProgress?.(progress);
    } else if (currentRun.status === 'queued') {
      onProgress?.({ label: 'Queued', revisionCount: null });
    } else if (currentRun.status === 'running') {
      onProgress?.({ label: 'Running', revisionCount: null });
    }
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
  onProgress?.(extractRunProgress(outputs));
  return outputs;
}

async function runViaLegacyExecute(inputs: Record<string, unknown>): Promise<AgentOutputs> {
  const payload = await requestWithFallback<unknown>('post', API_PATHS.legacyExecute, { data: { inputs } });
  return toOutputs(payload);
}

function getErrorMessage(error: unknown, fallback: string): string {
  const status = (error as { response?: { status?: number } })?.response?.status;
  if (status === 401) {
    return (
      'Unauthorized API request. Set `VITE_API_TOKEN` in `frontend/.env` ' +
      'and restart the frontend dev server.'
    );
  }

  const responseData = (error as { response?: { data?: unknown } })?.response?.data;
  if (typeof responseData === 'string' && responseData.trim()) {
    const text = responseData.trim();
    if (text.startsWith('<!DOCTYPE html') || text.startsWith('<html')) {
      return 'Server returned an HTML error page. Check backend logs for the root cause.';
    }
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

export const BookStudioPage: React.FC = () => {
  const [currentStep, setCurrentStep] = useState<Step>('concept');
  const [isSidebarOpen, setSidebarOpen] = useState(true);
  const [bookState, setBookState] = useState<BookState>(() => readState());
  const [transport, setTransport] = useState<'auto' | 'async' | 'legacy'>('auto');
  const [lastRun, setLastRun] = useState<string>('No runs yet.');
  const [runProgressLabel, setRunProgressLabel] = useState<string>('');
  const [runRevisionCount, setRunRevisionCount] = useState<number | null>(null);
  const [resettingStudio, setResettingStudio] = useState(false);

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
  const activeStep = steps.find((step) => step.id === currentStep);

  const updateRunProgress = (snapshot: RunProgressSnapshot | null) => {
    if (!snapshot) {
      setRunProgressLabel('');
      setRunRevisionCount(null);
      return;
    }
    setRunProgressLabel(snapshot.label);
    setRunRevisionCount(snapshot.revisionCount);
  };

  const logRun = (mode: Mode, outputs: AgentOutputs) => {
    const fallbackMsg = outputs.used_fallback ? ` | fallback ${formatFallbackStages(outputs.fallback_stages)}` : '';
    const msg = `${new Date().toLocaleTimeString()} | ${mode} | ${isSuccess(outputs) ? 'success' : 'error'}${fallbackMsg}${outputs.trace_id ? ` | trace ${outputs.trace_id}` : ''}`;
    setLastRun(msg);
    updateRunProgress(extractRunProgress(outputs));
    if (outputs.used_fallback) {
      toast(`Fallback used: ${formatFallbackStages(outputs.fallback_stages)}`, { icon: '⚠️' });
    }
    if (outputs.warnings?.length) toast(outputs.warnings[0], { icon: '⚠️' });
  };

  const executeAgent = async (mode: Mode, inputs: Record<string, unknown>): Promise<AgentOutputs> => {
    try {
      updateRunProgress({ label: 'Queued', revisionCount: null });
      setLastRun(`${new Date().toLocaleTimeString()} | ${mode} | running | async`);
      const outputs = await runViaAsyncApi(
        mode,
        bookState,
        setBookState,
        inputs,
        (snapshot) => updateRunProgress(snapshot),
      );
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
      updateRunProgress({ label: 'Legacy execution', revisionCount: null });
      const outputs = await runViaLegacyExecute(inputs);
      setTransport('legacy');
      updateRunProgress(null);
      return outputs;
    }
  };

  const resetStudio = async () => {
    if (resettingStudio) {
      return;
    }

    const hasBackendProject = Boolean(bookState.backendProjectId);
    const confirmationMessage = hasBackendProject
      ? 'Reset Studio will clear local autosave and permanently delete the linked backend project. This cannot be undone. Continue?'
      : 'Reset Studio will clear local autosave and restore defaults. Continue?';
    if (typeof window !== 'undefined' && !window.confirm(confirmationMessage)) {
      return;
    }

    setResettingStudio(true);
    try {
      let deleteWarning = '';
      if (hasBackendProject && bookState.backendProjectId) {
        try {
          await requestWithFallback<unknown>('delete', API_PATHS.projectDetail(bookState.backendProjectId));
        } catch (error) {
          deleteWarning = getErrorMessage(error, 'Linked backend project could not be deleted.');
        }
      }
      if (typeof window !== 'undefined') {
        window.localStorage.removeItem(STORAGE_KEY);
      }
      setBookState({
        ...DEFAULT_STATE,
        updatedAt: new Date().toISOString(),
      });
      setCurrentStep('concept');
      setTransport('auto');
      setLastRun('No runs yet.');
      updateRunProgress(null);
      if (deleteWarning) {
        toast.success('Studio reset locally.');
        toast(deleteWarning, { icon: '⚠️' });
      } else {
        toast.success(hasBackendProject ? 'Studio reset. Backend project deleted.' : 'Studio reset.');
      }
      // Shallow state update to show "Resetting" UX then hard reload for clean unmount/remount
      setTimeout(() => {
        if (typeof window !== 'undefined') window.location.reload();
      }, 1000);
    } catch (error) {
      toast.error(getErrorMessage(error, 'Reset failed. Existing state was kept.'));
    } finally {
      setResettingStudio(false);
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
    <div className="relative flex min-h-screen bg-slate-50 text-slate-800 font-sans">
      <Toaster position="top-right" />
      <motion.aside
        initial={{ width: 256 }}
        animate={{ width: isSidebarOpen ? 256 : 84 }}
        className="relative z-10 flex flex-col border-r border-slate-200 bg-white"
      >
        <div className="flex items-center justify-between border-b border-slate-100 p-4">
          {isSidebarOpen ? (
            <div>
              <div className="text-lg font-bold tracking-tight text-slate-900">Book Foundry</div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-widest mt-0.5">Writer Studio</div>
            </div>
          ) : (
            <div className="mx-auto text-sm font-bold tracking-widest text-slate-900">BF</div>
          )}
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            className="rounded-lg border border-transparent p-1.5 text-slate-400 transition hover:bg-slate-50 hover:text-slate-700"
          >
            {isSidebarOpen ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
          </button>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {steps.map((s) => (
            <button
              key={s.id}
              onClick={() => (s.enabled ? setCurrentStep(s.id) : toast.error('Complete previous steps first.'))}
              className={`flex w-full items-center rounded-xl px-4 py-3 transition-colors duration-200 ${
                currentStep === s.id
                  ? 'bg-indigo-50 text-indigo-700 font-semibold shadow-sm ring-1 ring-indigo-200/50'
                  : s.enabled
                    ? 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'
                    : 'cursor-not-allowed text-slate-300 font-medium'
              }`}
            >
              <span className={`mr-3 ${currentStep === s.id ? 'text-indigo-600' : ''}`}>{s.icon}</span>
              {isSidebarOpen && <span className="text-sm">{s.label}</span>}
            </button>
          ))}
        </nav>
        {isSidebarOpen && (
          <div className="m-4 rounded-xl border border-slate-100 bg-slate-50 p-4 text-xs text-slate-600">
            <div className="mb-1.5 font-semibold text-slate-900 flex justify-between">
              <span>Draft progress</span>
              <span className="text-indigo-600">{progress.pct}%</span>
            </div>
            <div className="text-slate-500 mb-3">{progress.done} of {progress.total || 0} chapters completed</div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
              <div
                className="h-full rounded-full bg-indigo-500 transition-all duration-500 ease-out"
                style={{ width: `${progress.pct}%` }}
              />
            </div>
          </div>
        )}
      </motion.aside>

      <main className="flex-1 overflow-y-auto bg-slate-50 p-4 md:p-8 lg:p-10">
        <div className="mx-auto w-full max-w-6xl">
          <div className="mb-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-slate-500">
              <span className="rounded-md bg-slate-100 px-2 py-1 text-slate-600">Writer Studio</span>
              <span className="rounded-md bg-indigo-50 px-2 py-1 text-indigo-700">{activeStep?.label || 'Concept'} Step</span>
            </div>
            <div className="mt-4 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <h1 className="text-3xl font-bold text-slate-900 md:text-4xl tracking-tight">{bookState.title || 'Untitled Project'}</h1>
                <p className="mt-1.5 text-sm font-medium text-slate-500">{bookState.genre} • {bookState.language} • {bookState.tone} • Target {bookState.length.toLocaleString()} words</p>
              </div>
              <div className="flex w-full max-w-[420px] flex-col gap-3 md:items-end">
                <div className="w-full rounded-xl border border-slate-100 bg-slate-50 px-4 py-3 text-xs text-slate-600 shadow-sm">
                  <div className="flex justify-between mb-1">
                    <span className="font-semibold text-slate-700">Storage</span>
                    <span>{transport}{bookState.backendProjectId ? ` • ${bookState.backendProjectId.slice(0, 8)}...` : ' • Local UI'}</span>
                  </div>
                  <div className="flex justify-between mb-1 text-slate-500">
                    <span>Last Saved</span>
                    <span>{new Date(bookState.updatedAt).toLocaleTimeString()}</span>
                  </div>
                  {runProgressLabel ? (
                    <div className="flex justify-between font-medium text-indigo-700">
                      <span>Status</span>
                      <span>{runProgressLabel}{runRevisionCount !== null ? ` (Rev ${runRevisionCount})` : ''}</span>
                    </div>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={resetStudio}
                  disabled={resettingStudio}
                  className="inline-flex items-center justify-center rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-600 shadow-sm transition-colors hover:bg-red-50 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {resettingStudio ? 'Resetting...' : 'Reset Studio'}
                </button>
              </div>
            </div>
          </div>
          <AnimatePresence mode="wait">
            <motion.div key={currentStep} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.22 }}>
              {renderStep()}
            </motion.div>
          </AnimatePresence>
        </div>
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
  const [kbBusy, setKbBusy] = useState(false);
  const [kbTitle, setKbTitle] = useState('');
  const [kbText, setKbText] = useState('');
  const [kbFile, setKbFile] = useState<File | null>(null);
  const [filePickerKey, setFilePickerKey] = useState(0);
  const [kbPriority, setKbPriority] = useState<SourcePriority>('supporting');
  const [knowledgeSummary, setKnowledgeSummary] = useState('No knowledge source uploaded yet.');
  const [setupStep, setSetupStep] = useState(1);
  const [wordCountInput, setWordCountInput] = useState(() => String(Math.max(300, Number(bookState.length) || 300)));
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantInput, setAssistantInput] = useState('');
  const [assistantCheckedChoices, setAssistantCheckedChoices] = useState<string[]>([]);
  const assistantMessages = bookState.assistantMessages || [];
  const assistantDraft = bookState.assistantDraft || {};
  const assistantMissing = bookState.assistantMissing || [];
  const assistantReadyToFinalize = !!bookState.assistantReadyToFinalize;
  const assistantNextField = bookState.assistantNextField || 'title';
  const assistantLastAppliedFields = Array.isArray(bookState.assistantLastAppliedFields)
    ? bookState.assistantLastAppliedFields
    : [];
  const assistantUserMessageCount = assistantMessages.filter(
    (msg) => msg.role === 'user' && msg.content.trim().length > 0,
  ).length;
  const assistantHasSubstantiveUserInput = assistantMessages.some((msg) => {
    if (msg.role !== 'user') {
      return false;
    }
    const text = msg.content.trim();
    if (!text) {
      return false;
    }
    return !/^(hi|hello|hey|ok|okay)$/i.test(text);
  });
  const assistantOnlyMissingTitle = assistantMissing.length === 1 && assistantMissing[0] === 'title';
  const showAssistantMissingWarning =
    assistantMissing.length > 0 &&
    (assistantMessages.length >= 5 || assistantHasSubstantiveUserInput) &&
    !(assistantOnlyMissingTitle && assistantUserMessageCount < 3);
  const finalizeSyncInFlightRef = useRef(false);
  const assistantViewportRef = useRef<HTMLDivElement | null>(null);

  const save = <K extends keyof BookState>(k: K, v: BookState[K]) => setBookState((p) => ({ ...p, [k]: v, updatedAt: new Date().toISOString() }));
  const toggleCollection = (key: 'frontMatter' | 'backMatter' | 'richElements', value: string) =>
    setBookState((prev) => {
      const existing = prev[key] || [];
      const next = existing.includes(value) ? existing.filter((item) => item !== value) : [...existing, value];
      return { ...prev, [key]: next, updatedAt: new Date().toISOString() };
    });

  const normalizeAssistantUpdates = (updates: Record<string, unknown>) => {
    const patch: Partial<BookState> = {};
    const toText = (v: unknown) => (typeof v === 'string' ? v.trim() : '');
    const toNumber = (v: unknown, fallback: number) => {
      const num = Number(v);
      return Number.isFinite(num) ? Math.max(300, Math.round(num)) : fallback;
    };
    const toList = (v: unknown) => {
      if (Array.isArray(v)) return v.map((item) => String(item).trim()).filter(Boolean);
      if (typeof v === 'string') return v.split(',').map((item) => item.trim()).filter(Boolean);
      return [];
    };

    if ('title' in updates) patch.title = toText(updates.title);
    if ('subtitle' in updates) patch.subtitle = toText(updates.subtitle);
    if ('genre' in updates) patch.genre = toText(updates.genre);
    if ('language' in updates) patch.language = toText(updates.language);
    if ('length' in updates) patch.length = toNumber(updates.length, bookState.length);
    if ('pageFeel' in updates) patch.pageFeel = toText(updates.pageFeel);
    if ('publishingIntent' in updates) patch.publishingIntent = toText(updates.publishingIntent);
    if ('audience' in updates) patch.audience = toText(updates.audience);
    if ('audienceKnowledgeLevel' in updates) patch.audienceKnowledgeLevel = toText(updates.audienceKnowledgeLevel);
    if ('culturalContext' in updates) patch.culturalContext = toText(updates.culturalContext);
    if ('bookPurpose' in updates) patch.bookPurpose = toText(updates.bookPurpose);
    if ('primaryCta' in updates) patch.primaryCta = toText(updates.primaryCta);
    if ('tone' in updates) patch.tone = toText(updates.tone);
    if ('writingStyle' in updates) patch.writingStyle = toText(updates.writingStyle);
    if ('pointOfView' in updates) patch.pointOfView = toText(updates.pointOfView);
    if ('tense' in updates) patch.tense = toText(updates.tense);
    if ('sentenceRhythm' in updates) patch.sentenceRhythm = toText(updates.sentenceRhythm);
    if ('vocabularyLevel' in updates) patch.vocabularyLevel = toText(updates.vocabularyLevel);
    if ('ghostwritingMode' in updates) patch.ghostwritingMode = Boolean(updates.ghostwritingMode);
    if ('booksToEmulate' in updates) patch.booksToEmulate = toText(updates.booksToEmulate);
    if ('styleReferencePassage' in updates) patch.styleReferencePassage = toText(updates.styleReferencePassage);
    if ('customInstructions' in updates) patch.customInstructions = toText(updates.customInstructions);
    if ('chapterLength' in updates) patch.chapterLength = toText(updates.chapterLength);
    if ('frontMatter' in updates) patch.frontMatter = toList(updates.frontMatter);
    if ('backMatter' in updates) patch.backMatter = toList(updates.backMatter);
    if ('richElements' in updates) patch.richElements = toList(updates.richElements);
    if ('contentBoundaries' in updates) patch.contentBoundaries = toText(updates.contentBoundaries);
    return patch;
  };

  const chapterLengthWords = CHAPTER_LENGTH_WORDS[bookState.chapterLength] || 3000;
  const estimatedChapters = Math.max(1, Math.round(bookState.length / chapterLengthWords));
  const missing = profileMissing(bookState);
  const completion = profileCompleteness(bookState);
  const activeStepTitle = STEP_TITLES[Math.max(0, Math.min(STEP_TITLES.length - 1, setupStep - 1))];
  const activeStepNote = STEP_NOTES[Math.max(0, Math.min(STEP_NOTES.length - 1, setupStep - 1))];
  const missingLabels = missing.map((field) => PROFILE_LABELS[field] || field);
  const assistantFocusField = assistantNextField.trim();
  const assistantUsesCheckboxChoices = isAssistantMultiSelectField(assistantFocusField);
  const assistantFocusLabel = assistantUsesCheckboxChoices
    ? (ASSISTANT_FIELD_LABELS[assistantFocusField] || 'Selections')
    : 'Quick Replies';
  const humanizeAssistantFieldKey = (field: string) =>
    field
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/^./, (c) => c.toUpperCase());
  const toAssistantFieldLabel = (field: string) =>
    ASSISTANT_FIELD_LABELS[field] || PROFILE_LABELS[field] || humanizeAssistantFieldKey(field);
  const pendingAssistantFieldLabels = Object.keys(assistantDraft)
    .filter((field) => field.trim().length > 0)
    .map(toAssistantFieldLabel);
  const pendingAssistantFieldPreviews = Object.entries(assistantDraft)
    .filter(([field]) => field.trim().length > 0)
    .map(([field, value]) => {
      let preview = '';
      if (Array.isArray(value)) {
        preview = value.map((item) => String(item).trim()).filter(Boolean).join(', ');
      } else if (typeof value === 'boolean') {
        preview = value ? 'Yes' : 'No';
      } else if (typeof value === 'number') {
        preview = Number.isFinite(value) ? value.toLocaleString() : String(value);
      } else if (typeof value === 'string') {
        preview = value.trim();
      } else if (value !== null && value !== undefined) {
        preview = String(value);
      }
      const trimmedPreview = preview.trim();
      return {
        field,
        label: toAssistantFieldLabel(field),
        preview: trimmedPreview.length > 84 ? `${trimmedPreview.slice(0, 84)}...` : trimmedPreview,
      };
    });
  const appliedAssistantFieldLabels = assistantLastAppliedFields
    .filter((field) => field.trim().length > 0)
    .map(toAssistantFieldLabel);
  const assistantQuickChoices = useMemo(() => {
    if (assistantUsesCheckboxChoices) {
      return quickChoicesForField(assistantFocusField, assistantReadyToFinalize);
    }

    const rawSuggestions = Array.isArray(bookState.assistantSuggestions) ? bookState.assistantSuggestions : [];
    const normalizedSuggestions = rawSuggestions
      .map((s) => String(s).trim())
      .filter((s) => s.length > 0 && s.length <= 80 && !s.endsWith('?'))
      .filter((value, index, arr) => arr.indexOf(value) === index)
      .slice(0, 3);

    if (normalizedSuggestions.length > 0) {
      return normalizedSuggestions.map((s) => ({ label: s, message: s }));
    }
    if (assistantReadyToFinalize) {
      return [quickChoice('Finalize brief', 'yes finalize')];
    }
    return [];
  }, [assistantFocusField, assistantReadyToFinalize, assistantUsesCheckboxChoices, bookState.assistantSuggestions]);
  const selectedQuickChoices = useMemo(
    () => assistantQuickChoices.filter((choice) => assistantCheckedChoices.includes(choice.label)),
    [assistantQuickChoices, assistantCheckedChoices],
  );

  useEffect(() => {
    if (!assistantViewportRef.current) {
      return;
    }
    assistantViewportRef.current.scrollTop = assistantViewportRef.current.scrollHeight;
  }, [assistantMessages, assistantBusy]);

  useEffect(() => {
    const normalized = String(Math.max(300, Number(bookState.length) || 300));
    setWordCountInput((prev) => (prev === normalized ? prev : normalized));
  }, [bookState.length]);

  useEffect(() => {
    setAssistantCheckedChoices([]);
  }, [assistantFocusField]);

  useEffect(() => {
    setAssistantCheckedChoices((prev) => prev.filter((label) => assistantQuickChoices.some((choice) => choice.label === label)));
  }, [assistantQuickChoices]);

  const askAssistant = async (message: string) => {
    const trimmed = message.trim();
    if (!trimmed) return;
    setAssistantBusy(true);

    const outgoing = [...assistantMessages, { role: 'user' as const, content: trimmed }];
    setBookState((p) => ({ ...p, assistantMessages: outgoing }));
    setAssistantInput('');

    try {
      const projectId = await ensureProject(bookState, setBookState);
      const response = await requestWithFallback<AssistantResponse>('post', API_PATHS.projectProfileAssistant(projectId), {
        data: {
          message: trimmed,
          conversation: outgoing,
          current_profile: {
            ...buildProfilePayload(bookState),
            ...assistantDraft,
          },
        },
      });

      const normalized = normalizeAssistantUpdates(response.field_updates || {});
      const nextDraft = { ...assistantDraft, ...normalized };
      const assistantReply = (response.assistant_reply || 'Captured. Let us continue.').trim();
      const updatedMessages = [...outgoing, { role: 'assistant' as const, content: assistantReply }];
      const dynamicSuggestions = Array.isArray(response.suggestions) ? response.suggestions : [];

      const missingRequired =
        Array.isArray(response.missing_required) && response.missing_required.length > 0
          ? response.missing_required
          : profileMissingFromPayload({
              ...buildProfilePayload(bookState),
              ...nextDraft,
            });

      const suggestedNextField =
        typeof response.next_field === 'string' && response.next_field.trim()
          ? response.next_field.trim()
          : missingRequired[0] || '';

      if (response.is_finalized) {
        const finalizedAt = new Date().toISOString();
        const appliedAssistantFields = Object.keys(nextDraft).filter(Boolean);
        const finalizedState: BookState = {
          ...bookState,
          ...nextDraft,
          updatedAt: finalizedAt,
        };

        setBookState((prev) => ({
          ...prev,
          ...nextDraft,
          assistantMessages: updatedMessages,
          assistantDraft: {},
          assistantReadyToFinalize: false,
          assistantNextField: '',
          assistantMissing: [],
          assistantSuggestions: [],
          assistantLastAppliedFields: appliedAssistantFields,
          updatedAt: finalizedAt,
        }));
        toast.success('Finalized. Fields have been auto-filled from the conversation.');
        if (!finalizeSyncInFlightRef.current) {
          finalizeSyncInFlightRef.current = true;
          ensureProject(finalizedState, setBookState)
            .catch((syncError) => {
              toast.error(getErrorMessage(syncError, 'Finalized locally, but backend sync failed.'));
            })
            .finally(() => {
              finalizeSyncInFlightRef.current = false;
            });
        }
      } else {
        setBookState((prev) => ({
          ...prev,
          assistantMessages: updatedMessages,
          assistantDraft: nextDraft,
          assistantNextField: suggestedNextField,
          assistantMissing: missingRequired,
          assistantReadyToFinalize: missingRequired.length === 0,
          assistantSuggestions: dynamicSuggestions,
          updatedAt: new Date().toISOString(),
        }));
      }
    } catch (error) {
      const errorMsg = getErrorMessage(error, 'Assistant request failed.');
      setBookState((prev) => ({
        ...prev,
        assistantMessages: [...(prev.assistantMessages || []), { role: 'assistant', content: 'I could not process that right now. Please continue manually for this step.' }],
      }));
      toast.error(errorMsg);
    } finally {
      setAssistantBusy(false);
    }
  };

  const submitAssistant = () => {
    const trimmed = assistantInput.trim();
    if (!trimmed || assistantBusy) {
      return;
    }
    askAssistant(trimmed);
  };

  const finalizeAssistantDraft = () => {
    if (assistantBusy || !assistantReadyToFinalize) {
      return;
    }
    askAssistant('yes finalize');
  };

  const toggleAssistantCheckedChoice = (label: string) => {
    setAssistantCheckedChoices((prev) =>
      prev.includes(label) ? prev.filter((item) => item !== label) : [...prev, label]
    );
  };

  const submitAssistantCheckedChoices = () => {
    if (!assistantUsesCheckboxChoices || assistantBusy) {
      return;
    }
    const message = buildAssistantMultiSelectMessage(assistantFocusField, selectedQuickChoices);
    if (!message.trim()) {
      return;
    }
    askAssistant(message);
    setAssistantCheckedChoices([]);
  };

  const handleWordCountChange = (raw: string) => {
    if (!/^\d*$/.test(raw)) {
      return;
    }
    setWordCountInput(raw);
    if (!raw.trim()) {
      return;
    }
    const parsed = parseInt(raw, 10);
    if (Number.isFinite(parsed) && parsed >= 300) {
      save('length', parsed);
    }
  };

  const commitWordCountInput = () => {
    const parsed = parseInt(wordCountInput, 10);
    const normalized = Number.isFinite(parsed) ? Math.max(300, parsed) : Math.max(300, Number(bookState.length) || 300);
    setWordCountInput(String(normalized));
    if (bookState.length !== normalized) {
      save('length', normalized);
    }
  };

  const saveKnowledgeText = async () => {
    if (!bookState.title.trim()) {
      toast.error('Set a book title first.');
      return;
    }
    if (!kbText.trim()) {
      toast.error('Add knowledge text first.');
      return;
    }
    setKbBusy(true);
    try {
      const projectId = await ensureProject(bookState, setBookState);
      const title = kbTitle.trim() || `Knowledge Note ${new Date().toLocaleDateString()}`;
      const source = await requestWithFallback<SourceDocument>('post', API_PATHS.projectSources(projectId), {
        data: {
          title,
          source_type: 'note',
          content: kbText.trim(),
          metadata_json: {
            ingest: 'manual_text',
            priority: kbPriority,
          }
        }
      });
      const chunks = source.index_stats?.chunks_indexed ?? 0;
      setKnowledgeSummary(`Saved "${source.title}" (${words(kbText)} words, ${chunks} indexed chunks).`);
      setKbText('');
      setKbTitle('');
      toast.success('Knowledge text saved.');
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to save knowledge text.'));
    } finally {
      setKbBusy(false);
    }
  };

  const uploadKnowledgeFile = async () => {
    if (!bookState.title.trim()) {
      toast.error('Set a book title first.');
      return;
    }
    if (!kbFile) {
      toast.error('Choose a file first.');
      return;
    }
    setKbBusy(true);
    try {
      const projectId = await ensureProject(bookState, setBookState);
      const formData = new FormData();
      formData.append('file', kbFile);
      if (kbTitle.trim()) {
        formData.append('title', kbTitle.trim());
      }
      formData.append('priority', kbPriority);
      const response = await axiosInstance.post<SourceDocument>(
        API_PATHS.projectKnowledgeUpload(projectId)[0],
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' }
        }
      );
      const source = response.data;
      const chunks = source.index_stats?.chunks_indexed ?? 0;
      setKnowledgeSummary(`Uploaded "${source.title}" (${kbFile.name}) with ${chunks} indexed chunks.`);
      setKbFile(null);
      setKbTitle('');
      setFilePickerKey((k) => k + 1);
      toast.success('Knowledge file uploaded.');
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to upload knowledge file.'));
    } finally {
      setKbBusy(false);
    }
  };

  const generate = async () => {
    if (!bookState.title.trim()) return toast.error('Book title is required.');
    const requiredMissing = profileMissing(bookState);
    if (requiredMissing.length) {
      const labels = requiredMissing.map((field) => PROFILE_LABELS[field] || field).join(', ');
      toast.error(`Complete required fields before generate: ${labels}`);
      return;
    }
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

  const renderManualStep = () => {
    if (setupStep === 1) {
      return (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <InputGroup label="Book Title" value={bookState.title} onChange={(v) => save('title', v)} placeholder="e.g. The Focused Mind" />
          <InputGroup label="Subtitle (Optional)" value={bookState.subtitle} onChange={(v) => save('subtitle', v)} placeholder="A practical guide to deep work" />
          <SelectGroup label="Genre" value={bookState.genre} onChange={(v) => save('genre', v)} options={GENRE_OPTIONS} />
          <SelectGroup label="Language" value={bookState.language} onChange={(v) => save('language', v)} options={LANGUAGE_OPTIONS} />
          <div>
            <InputGroup
              label="Target Word Count"
              type="number"
              value={wordCountInput}
              onChange={handleWordCountChange}
              onBlur={commitWordCountInput}
              min={300}
              step={500}
              inputMode="numeric"
              placeholder="e.g. 4000 or 30000"
            />
            <p className="mt-1.5 text-xs text-slate-500">
              Type any value directly (for example `4000`, `5000`, `30000`). Minimum is 300 words.
            </p>
          </div>
          <SelectGroup label="Page Feel" value={bookState.pageFeel} onChange={(v) => save('pageFeel', v)} options={PAGE_FEEL_OPTIONS} />
          <div className="md:col-span-2">
            <SelectGroup label="Publishing Intent" value={bookState.publishingIntent} onChange={(v) => save('publishingIntent', v)} options={PUBLISHING_INTENT_OPTIONS} />
          </div>
        </div>
      );
    }
    if (setupStep === 2) {
      return (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <InputGroup label="Target Audience" value={bookState.audience} onChange={(v) => save('audience', v)} placeholder="startup founders, college students..." />
          <SelectGroup label="Audience Knowledge Level" value={bookState.audienceKnowledgeLevel} onChange={(v) => save('audienceKnowledgeLevel', v)} options={KNOWLEDGE_LEVEL_OPTIONS} />
          <InputGroup label="Cultural / Geographic Context (Optional)" value={bookState.culturalContext} onChange={(v) => save('culturalContext', v)} placeholder="Pakistani market, US academic..." />
          <SelectGroup label="Book Purpose" value={bookState.bookPurpose} onChange={(v) => save('bookPurpose', v)} options={PURPOSE_OPTIONS} />
          <div className="md:col-span-2">
            <InputGroup label="Primary CTA After Reading (Optional)" value={bookState.primaryCta} onChange={(v) => save('primaryCta', v)} placeholder="hire me, apply this framework..." />
          </div>
        </div>
      );
    }
    if (setupStep === 3) {
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <SelectGroup label="Tone" value={bookState.tone} onChange={(v) => save('tone', v)} options={TONE_OPTIONS} />
            <SelectGroup label="Writing Style" value={bookState.writingStyle} onChange={(v) => save('writingStyle', v)} options={WRITING_STYLE_OPTIONS} />
            <SelectGroup label="Point of View" value={bookState.pointOfView} onChange={(v) => save('pointOfView', v)} options={POV_OPTIONS} />
            <SelectGroup label="Tense (Optional)" value={bookState.tense} onChange={(v) => save('tense', v)} options={TENSE_OPTIONS} />
            <SelectGroup label="Sentence Rhythm" value={bookState.sentenceRhythm} onChange={(v) => save('sentenceRhythm', v)} options={RHYTHM_OPTIONS} />
            <SelectGroup label="Vocabulary Level" value={bookState.vocabularyLevel} onChange={(v) => save('vocabularyLevel', v)} options={VOCAB_OPTIONS} />
            <div>
              <label className="mb-2 block text-[10px] font-bold uppercase tracking-widest text-slate-500">Author Voice Mode</label>
              <button
                type="button"
                onClick={() => save('ghostwritingMode', !bookState.ghostwritingMode)}
                className={`w-full rounded-lg px-4 py-2 text-sm font-semibold shadow-sm transition-colors ${bookState.ghostwritingMode ? 'border border-indigo-600 bg-indigo-600 text-white' : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'}`}
              >
                {bookState.ghostwritingMode ? 'Write in my voice (personal experience)' : 'Neutral authorial voice'}
              </button>
              <p className="mt-1.5 text-xs text-slate-500">
                Use personal first-hand voice when writing as/for a specific author.
              </p>
            </div>
          </div>
          <div>
            <InputGroup
              label="Books to Emulate (Optional)"
              value={bookState.booksToEmulate}
              onChange={(v) => save('booksToEmulate', v)}
              placeholder="Atomic Habits by James Clear, Deep Work by Cal Newport"
            />
            <p className="mt-1.5 text-xs text-slate-500">Include author names for better voice matching.</p>
          </div>
          <div>
            <TextAreaGroup
              label="Style Reference Passage (Optional)"
              value={bookState.styleReferencePassage}
              onChange={(v) => save('styleReferencePassage', v)}
              placeholder="Paste a paragraph in your desired voice..."
            />
            <p className="mt-1.5 text-xs text-slate-500">Strongest style signal: paste a paragraph that sounds like the book you want.</p>
          </div>
          <div>
            <TextAreaGroup
              label="Custom Instructions"
              value={bookState.customInstructions}
              onChange={(v) => save('customInstructions', v)}
              placeholder="Constraints, chapter structure rules, topics to emphasize, or anything the AI should always remember."
            />
            <p className="mt-1.5 text-xs text-slate-500">Use this for recurring constraints, emphasis rules, and non-negotiables.</p>
          </div>
        </div>
      );
    }
    if (setupStep === 4) {
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_auto] md:items-end">
            <SelectGroup label="Chapter Length" value={bookState.chapterLength} onChange={(v) => save('chapterLength', v)} options={CHAPTER_LENGTH_OPTIONS} />
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 shadow-sm">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Estimated Chapters</div>
              <div className="mt-1 text-sm font-semibold text-slate-900">~{estimatedChapters} chapters</div>
              <div className="mt-0.5 text-[11px] text-slate-500">From word target + chapter length</div>
            </div>
          </div>
          <MultiChoiceGroup label="Front Matter" options={FRONT_MATTER_OPTIONS} values={bookState.frontMatter} onToggle={(value) => toggleCollection('frontMatter', value)} />
          <MultiChoiceGroup label="Back Matter" options={BACK_MATTER_OPTIONS} values={bookState.backMatter} onToggle={(value) => toggleCollection('backMatter', value)} />
          <MultiChoiceGroup label="Rich Elements to Include" options={RICH_ELEMENT_OPTIONS} values={bookState.richElements} onToggle={(value) => toggleCollection('richElements', value)} />
          <TextAreaGroup label="Content Boundaries (Optional)" value={bookState.contentBoundaries} onChange={(v) => save('contentBoundaries', v)} placeholder="Topics to avoid, names not to mention, sensitive zones..." />
        </div>
      );
    }
    return (
      <div className="space-y-4">
        <div className="rounded-2xl border border-cyan-100/90 bg-[linear-gradient(140deg,rgba(236,254,255,0.85),rgba(255,255,255,0.85))] p-3 text-xs text-[#4d676b]">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#3f6469]">Knowledge Base Before Generate</div>
          Supported files: `.txt`, `.md`, `.pdf`, `.docx`. Add files and/or seed text. Priority controls how strongly sources influence planning and generation.
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <InputGroup
            label="Source Title (Optional)"
            value={kbTitle}
            onChange={setKbTitle}
            placeholder="e.g. Product Notes v1"
          />
          <SelectGroup
            label="Source Priority"
            value={kbPriority}
            onChange={(v) => setKbPriority(v as SourcePriority)}
            options={['primary', 'supporting', 'tone-only']}
          />
        </div>
        <TextAreaGroup label="Knowledge Text" value={kbText} onChange={setKbText} placeholder="Paste your initial ideas, notes, or source material..." />
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          <button
            type="button"
            onClick={saveKnowledgeText}
            disabled={kbBusy || !kbText.trim()}
            className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${
              kbBusy || !kbText.trim()
                ? 'cursor-not-allowed bg-[#d6cfbd] text-[#736b5e]'
                : 'bg-gradient-to-r from-[#0ea5a2] to-[#0b8a88] text-white shadow-[0_12px_22px_-14px_rgba(14,165,162,0.8)] hover:-translate-y-0.5 hover:from-[#0c9a98] hover:to-[#0a7a78]'
            }`}
          >
            Save Text
          </button>
          <label className="cursor-pointer rounded-xl border border-cyan-300/75 bg-cyan-50/85 px-4 py-2 text-center text-sm font-semibold text-[#0b7285] transition hover:-translate-y-0.5 hover:bg-cyan-100">
            Select File
            <input
              key={filePickerKey}
              type="file"
              accept=".txt,.md,.pdf,.docx,.doc"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0] || null;
                setKbFile(file);
              }}
            />
          </label>
          <button
            type="button"
            onClick={uploadKnowledgeFile}
            disabled={kbBusy || !kbFile}
            className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${
              kbBusy || !kbFile
                ? 'cursor-not-allowed bg-[#d6cfbd] text-[#736b5e]'
                : 'bg-gradient-to-r from-[#2563eb] to-[#1d4ed8] text-white shadow-[0_12px_22px_-14px_rgba(37,99,235,0.8)] hover:-translate-y-0.5 hover:from-[#1d4ed8] hover:to-[#1e40af]'
            }`}
          >
            Upload File
          </button>
        </div>
        <div className="rounded-xl border border-cyan-200/75 bg-cyan-50/72 px-3 py-2 text-[#355a60] shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#5c7a7e]">Current Source</div>
          <div className="text-sm font-medium">{kbFile ? kbFile.name : 'No file selected'}</div>
          <p className="mt-1 text-xs">{knowledgeSummary}</p>
        </div>
      </div>
    );
  };

  return (
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 lg:grid-cols-12">
      <div className="lg:col-span-7">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-slate-900 md:text-3xl">Concept Studio</h2>
            <p className="mt-1.5 text-sm text-slate-500">Fill manually or use Assistant. Both update the same brief fields.</p>
          </div>
          <span className="rounded-md bg-slate-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-600">
            Step {setupStep} of 5
          </span>
        </div>

        <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {STEP_TITLES.map((label, index) => {
            const stepNumber = index + 1;
            const isActive = setupStep === stepNumber;
            const isComplete = setupStep > stepNumber;
            return (
              <button
                key={label}
                type="button"
                onClick={() => setSetupStep(stepNumber)}
                className={`group flex flex-col items-center justify-center rounded-xl border p-3 text-center transition-colors ${
                  isActive
                    ? 'border-indigo-200 bg-indigo-50 text-indigo-700 shadow-sm ring-1 ring-indigo-200/50'
                    : isComplete
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100/50'
                      : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                }`}
              >
                <div
                  className={`mb-1.5 flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${
                    isActive
                      ? 'bg-indigo-600 text-white'
                      : isComplete
                        ? 'bg-emerald-500 text-white'
                        : 'bg-slate-100 text-slate-400 group-hover:bg-slate-200'
                  }`}
                >
                  {stepNumber}
                </div>
                <span className="text-[10px] font-semibold uppercase tracking-wider">{label}</span>
              </button>
            );
          })}
        </div>

        <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-5">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-indigo-600">Step {setupStep}</div>
              <h3 className="mt-1 text-lg font-bold text-slate-900">{activeStepTitle}</h3>
              <p className="mt-1 text-sm text-slate-500">{activeStepNote}</p>
            </div>
          </div>
          {renderManualStep()}
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Readiness</div>
                <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${completion === 100 ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                  {completion}% complete
                </span>
              </div>
              <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-indigo-500 transition-all duration-300 ease-out"
                  style={{ width: `${completion}%` }}
                />
              </div>
              {missingLabels.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {missingLabels.slice(0, 3).map((label) => (
                    <span key={label} className="rounded-md bg-amber-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-amber-700">
                      {label}
                    </span>
                  ))}
                  {missingLabels.length > 3 && (
                    <span className="rounded-md bg-amber-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-amber-700">
                      +{missingLabels.length - 3} more
                    </span>
                  )}
                </div>
              ) : (
                <div className="mt-3 text-xs font-medium text-emerald-600">All required fields are complete.</div>
              )}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setSetupStep((prev) => Math.max(1, prev - 1))}
                  disabled={setupStep === 1}
                  className="flex items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="Previous step"
                >
                  <ChevronLeft size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => setSetupStep((prev) => Math.min(5, prev + 1))}
                  disabled={setupStep === 5}
                  className="flex items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="Next step"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
              <button
                onClick={generate}
                disabled={loading || !bookState.title.trim()}
                className="flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-white" /> : <Wand2 size={16} />}
                Generate Blueprint
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-6 lg:col-span-5">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4">
            <span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">
              Conversational Auto-Fill
            </span>
            <h3 className="mt-3 text-lg font-bold text-slate-900">Assistant Intake</h3>
            <p className="mt-1 text-sm text-slate-500">Chat naturally or tap options. Type <span className="font-bold text-slate-700">finalize</span> to apply values.</p>
          </div>

          <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-white px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-500 shadow-sm">
                Pending: {pendingAssistantFieldLabels.length}
              </span>
              <span className="rounded-md bg-white px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-500 shadow-sm">
                Applied: {appliedAssistantFieldLabels.length}
              </span>
              <span className={`rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-widest shadow-sm ${assistantReadyToFinalize ? 'bg-emerald-50 text-emerald-700' : 'bg-white text-slate-500'}`}>
                {assistantReadyToFinalize ? 'Ready to finalize' : 'Collecting brief'}
              </span>
            </div>

            {(pendingAssistantFieldLabels.length > 0 || appliedAssistantFieldLabels.length > 0) && (
              <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm">
                  <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">Pending Capture</div>
                  {pendingAssistantFieldLabels.length > 0 ? (
                    <div>
                      <div className="flex flex-wrap gap-1.5">
                      {pendingAssistantFieldLabels.slice(0, 5).map((label) => (
                        <span key={`pending-${label}`} className="rounded-md bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                          {label}
                        </span>
                      ))}
                      {pendingAssistantFieldLabels.length > 5 ? (
                        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                          +{pendingAssistantFieldLabels.length - 5} more
                        </span>
                      ) : null}
                    </div>
                      {pendingAssistantFieldPreviews.length > 0 && (
                        <div className="mt-2 space-y-1">
                          {pendingAssistantFieldPreviews.slice(0, 3).map((item) => (
                            <div key={`pending-preview-${item.field}`} className="text-[11px] leading-relaxed text-slate-600">
                              <span className="font-semibold text-slate-700">{item.label}:</span>{' '}
                              {item.preview || 'Captured'}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500">No pending captured values.</div>
                  )}
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm">
                  <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">Applied To Form</div>
                  {appliedAssistantFieldLabels.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {appliedAssistantFieldLabels.slice(0, 5).map((label) => (
                        <span key={`applied-${label}`} className="rounded-md bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                          {label}
                        </span>
                      ))}
                      {appliedAssistantFieldLabels.length > 5 ? (
                        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                          +{appliedAssistantFieldLabels.length - 5} more
                        </span>
                      ) : null}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500">Nothing applied yet. Finalize to sync with the form.</div>
                  )}
                </div>
              </div>
            )}

            {assistantReadyToFinalize && (
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-2.5">
                <div className="text-xs font-medium text-emerald-700">
                  Ready to apply captured values. Remaining optional fields can stay at defaults.
                </div>
                <button
                  type="button"
                  onClick={finalizeAssistantDraft}
                  disabled={assistantBusy}
                  className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Finalize & Apply
                </button>
              </div>
            )}

            <div ref={assistantViewportRef} className="max-h-[300px] space-y-3 overflow-y-auto rounded-lg border border-slate-200 bg-white p-3 shadow-inner">
              {assistantMessages.map((msg, index) => (
                <div key={`${msg.role}-${index}`} className={`flex ${msg.role === 'assistant' ? 'justify-start' : 'justify-end'}`}>
                  <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${msg.role === 'assistant' ? 'bg-slate-100 text-slate-800' : 'bg-indigo-600 text-white'}`}>
                    <div className="mb-0.5 text-[10px] font-bold uppercase tracking-wider opacity-60">{msg.role}</div>
                    <div className="whitespace-pre-wrap">{msg.content}</div>
                  </div>
                </div>
              ))}
              {assistantBusy && (
                <div className="flex justify-start">
                  <div className="rounded-lg bg-slate-100 px-3 py-2 text-xs font-medium text-slate-500">
                    Assistant is thinking...
                  </div>
                </div>
              )}
            </div>

            {assistantQuickChoices.length > 0 && (
              <div className="mt-3">
                <div className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  Quick Choices: {assistantFocusLabel}
                </div>
                {assistantUsesCheckboxChoices ? (
                  <div className="space-y-2">
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {assistantQuickChoices.map((choice, index) => {
                        const checked = assistantCheckedChoices.includes(choice.label);
                        return (
                          <label
                            key={`${choice.label}-${index}`}
                            className={`flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-2 text-xs font-semibold shadow-sm transition-colors ${
                              checked
                                ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
                                : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                            } ${assistantBusy ? 'cursor-not-allowed opacity-50' : ''}`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={assistantBusy}
                              onChange={() => toggleAssistantCheckedChoice(choice.label)}
                              className="h-3.5 w-3.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                            />
                            <span>{choice.label}</span>
                          </label>
                        );
                      })}
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[10px] font-medium text-slate-500">
                        Select one or more, then apply.
                      </div>
                      <button
                        type="button"
                        disabled={assistantBusy || selectedQuickChoices.length === 0}
                        onClick={submitAssistantCheckedChoices}
                        className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Apply Selected
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {assistantQuickChoices.map((choice, index) => (
                      <button
                        key={`${choice.label}-${index}`}
                        type="button"
                        disabled={assistantBusy}
                        onClick={() => askAssistant(choice.message)}
                        className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-600 shadow-sm transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {choice.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {showAssistantMissingWarning && (
              <div className="mt-3 text-xs text-amber-600">
                <span className="font-semibold">Missing:</span> {assistantMissing.map((field) => PROFILE_LABELS[field] || field).join(', ')}
              </div>
            )}
            
            <div className="mt-3 flex gap-2">
              <input
                type="text"
                value={assistantInput}
                onChange={(e) => setAssistantInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    submitAssistant();
                  }
                }}
                placeholder="Type your reply..."
                className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition-colors focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
              <button
                type="button"
                onClick={submitAssistant}
                disabled={assistantBusy || !assistantInput.trim()}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {assistantBusy ? '...' : 'Send'}
              </button>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h4 className="mb-4 text-base font-bold text-slate-900">Planning Snapshot</h4>
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Chapters</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{estimatedChapters}</div>
            </div>
            <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Word Target</div>
              <div className="mt-1 text-2xl font-bold text-slate-900">{bookState.length.toLocaleString()}</div>
            </div>
          </div>
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
  if (!bookState.outline) return <div className="rounded-3xl border border-white/80 bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(236,254,250,0.88),rgba(255,244,226,0.92))] p-8 text-center shadow-[0_14px_40px_-24px_rgba(8,47,73,0.34)] backdrop-blur-xl">No outline yet.</div>;
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
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 lg:grid-cols-12">
      <div className="lg:col-span-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-slate-900 md:text-3xl">Outline Architect</h2>
            <p className="mt-1.5 text-sm text-slate-500">Review, edit, and finalize your book's structure before drafting.</p>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-4">
            <h3 className="text-lg font-bold text-slate-900">Book Structure</h3>
            <button
              onClick={onNext}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700"
            >
              Approve & Draft
            </button>
          </div>
          <div className="mb-6">
            <label className="mb-2 block text-[10px] font-bold uppercase tracking-widest text-slate-500">Synopsis</label>
            <textarea
              value={bookState.outline.synopsis}
              onChange={(e) => setBookState((p) => ({ ...p, outline: { ...p.outline!, synopsis: e.target.value }, updatedAt: new Date().toISOString() }))}
              className="min-h-[96px] w-full resize-y rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-900 outline-none transition-colors focus:border-indigo-500 focus:bg-white focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div className="space-y-4">
            <label className="block text-[10px] font-bold uppercase tracking-widest text-slate-500">Chapters</label>
            {bookState.outline.chapters.map((c) => (
              <div key={c.number} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-slate-400">Chapter {c.number}</div>
                <input
                  value={c.title}
                  onChange={(e) => updateTitle(c.number, e.target.value)}
                  className="mb-3 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-900 outline-none transition-colors focus:border-indigo-500 focus:bg-white focus:ring-1 focus:ring-indigo-500"
                />
                <ul className="list-inside list-disc space-y-1 text-sm text-slate-600">
                  {c.bullet_points.map((bp, i) => (
                    <li key={i}>{bp}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-6 lg:col-span-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4">
            <span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">
              Refinement Engine
            </span>
            <h3 className="mt-3 text-lg font-bold text-slate-900">Outline Assistant</h3>
            <p className="mt-1 text-sm text-slate-500">Ask the AI to modify the structure instead of rewriting manually.</p>
          </div>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="e.g. add more practical examples in middle chapters."
            className="h-32 w-full resize-none rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-900 outline-none transition-colors focus:border-indigo-500 focus:bg-white focus:ring-1 focus:ring-indigo-500"
          />
          <button
            onClick={refine}
            disabled={loading || !feedback.trim()}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-white" /> : <Wand2 size={14} />}
            Refine Outline
          </button>
        </div>
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
  if (!bookState.outline) return <div className="rounded-3xl border border-white/80 bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(236,254,250,0.88),rgba(255,244,226,0.92))] p-8 text-center shadow-[0_14px_40px_-24px_rgba(8,47,73,0.34)] backdrop-blur-xl">No outline available.</div>;
  const current = bookState.outline.chapters.find((c) => c.number === bookState.currentChapterId) || null;
  const content = current ? bookState.chaptersContent[current.number] || '' : '';
  const currentReviewTelemetry = current ? bookState.chapterReviewTelemetry[current.number] || null : null;
  const gen = async (n: number) => {
    setLoading(true);
    try {
      const inputs = { mode: 'chapter', ...commonInputs(bookState), outline: bookState.outline, chapter_number: n };
      const outputs = await executeAgent('chapter', inputs);
      onRun('chapter', outputs);
      if (isSuccess(outputs) && outputs.chapter?.content) {
        const reviewTelemetry = extractChapterReviewTelemetry(outputs);
        setBookState((p) => ({
          ...p,
          chaptersContent: { ...p.chaptersContent, [n]: outputs.chapter?.content || '' },
          chapterReviewTelemetry: reviewTelemetry
            ? { ...p.chapterReviewTelemetry, [n]: reviewTelemetry }
            : p.chapterReviewTelemetry,
          currentChapterId: n,
          updatedAt: new Date().toISOString()
        }));
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
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm lg:col-span-3">
        <div className="border-b border-slate-100 px-4 py-3 font-bold text-slate-900">Chapters</div>
        <div className="max-h-[56vh] space-y-1 overflow-y-auto p-2">
          {bookState.outline.chapters.map((c) => (
            <button
              key={c.number}
              onClick={() => setBookState((p) => ({ ...p, currentChapterId: c.number, updatedAt: new Date().toISOString() }))}
              className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                bookState.currentChapterId === c.number
                  ? 'bg-indigo-50 font-semibold text-indigo-700 shadow-sm ring-1 ring-indigo-200/50'
                  : 'font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900'
              }`}
            >
              <span className="truncate">
                {c.number}. {c.title}
              </span>
              <span className={`h-2 w-2 rounded-full ${bookState.chaptersContent[c.number]?.trim() ? 'bg-emerald-500' : 'bg-slate-300'}`} />
            </button>
          ))}
        </div>
      </div>

      <div className="relative flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm lg:col-span-6">
        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-3">
          <div>
            <div className="text-sm font-bold text-slate-900">{current?.title || 'Select chapter'}</div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{words(content)} words | {totalWords} total</div>
          </div>
          <div className="flex gap-2">
            <button onClick={() => toast.success('Saved locally.')} className="rounded-md border border-slate-200 bg-white p-1.5 text-slate-500 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-700">
              <Save size={16} />
            </button>
            <button onClick={copy} className="rounded-md border border-slate-200 bg-white p-1.5 text-slate-500 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-700">
              <FileText size={16} />
            </button>
            <button onClick={dl} className="rounded-md border border-slate-200 bg-white p-1.5 text-slate-500 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-700">
              <Download size={16} />
            </button>
          </div>
        </div>
        {loading && <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/50 backdrop-blur-sm"><span className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600" /></div>}
        <textarea
          value={content}
          onChange={(e) =>
            current &&
            setBookState((p) => ({
              ...p,
              chaptersContent: { ...p.chaptersContent, [current.number]: e.target.value },
              updatedAt: new Date().toISOString()
            }))
          }
          className="h-[56vh] w-full resize-none border-none bg-transparent p-6 text-base leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 focus:ring-0"
          placeholder="Generate chapter then edit manually."
        />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-3">
        <div className="mb-4 text-[10px] font-bold uppercase tracking-widest text-slate-500">Draft Controls</div>
        <button
          onClick={() => current && gen(current.number)}
          disabled={loading || !current}
          className={`mb-3 flex w-full items-center justify-center gap-2 rounded-lg py-2 text-sm font-semibold shadow-sm transition-colors ${
            loading || !current
              ? 'cursor-not-allowed bg-slate-100 text-slate-400'
              : 'bg-indigo-600 text-white hover:bg-indigo-700'
          }`}
        >
          {loading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-white" /> : <Wand2 size={14} />} {content.trim() ? 'Regenerate' : 'Generate'} Current
        </button>
        <button
          onClick={onNext}
          className="w-full rounded-lg border border-slate-200 bg-white py-2 text-sm font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50"
        >
          Go To Export
        </button>
        {currentReviewTelemetry && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Latest Review</div>
              <div className="text-[10px] font-semibold text-slate-500">
                {new Date(currentReviewTelemetry.generatedAt).toLocaleTimeString()}
              </div>
            </div>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {currentReviewTelemetry.score !== null && (
                <span className={`rounded-md px-2 py-1 text-[10px] font-bold ${
                  currentReviewTelemetry.score >= 85
                    ? 'bg-emerald-50 text-emerald-700'
                    : currentReviewTelemetry.score >= 70
                      ? 'bg-amber-50 text-amber-700'
                      : 'bg-rose-50 text-rose-700'
                }`}>
                  Score {currentReviewTelemetry.score}
                </span>
              )}
              {currentReviewTelemetry.revisionCount !== null && (
                <span className="rounded-md bg-white px-2 py-1 text-[10px] font-bold text-slate-700 ring-1 ring-slate-200">
                  Revisions {currentReviewTelemetry.revisionCount}
                </span>
              )}
              {currentReviewTelemetry.runMs !== null && (
                <span className="rounded-md bg-white px-2 py-1 text-[10px] font-bold text-slate-700 ring-1 ring-slate-200">
                  {Math.max(0, Math.round(currentReviewTelemetry.runMs / 1000))}s
                </span>
              )}
              {currentReviewTelemetry.guardrailFail && (
                <span className="rounded-md bg-amber-50 px-2 py-1 text-[10px] font-bold text-amber-700">
                  Guardrail Trigger
                </span>
              )}
              {currentReviewTelemetry.profileComplianceFail && (
                <span className="rounded-md bg-indigo-50 px-2 py-1 text-[10px] font-bold text-indigo-700">
                  Profile Drift
                </span>
              )}
              {currentReviewTelemetry.usedFallback && (
                <span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-700">
                  Fallback
                </span>
              )}
            </div>
            {(currentReviewTelemetry.wordCount !== null || currentReviewTelemetry.minimumWordCount !== null) && (
              <div className="mb-2 text-xs text-slate-600">
                Word count {currentReviewTelemetry.wordCount ?? '-'}
                {currentReviewTelemetry.minimumWordCount !== null ? ` / min ${currentReviewTelemetry.minimumWordCount}` : ''}
              </div>
            )}
            {currentReviewTelemetry.issues.length > 0 && (
              <div className="mb-2">
                <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">Review Issues</div>
                <ul className="list-inside list-disc space-y-1 text-xs leading-relaxed text-slate-600">
                  {currentReviewTelemetry.issues.slice(0, 5).map((issue, index) => (
                    <li key={`${issue}-${index}`}>{issue}</li>
                  ))}
                </ul>
              </div>
            )}
            {currentReviewTelemetry.critique && (
              <div className="rounded-md border border-slate-200 bg-white p-2 text-xs leading-relaxed text-slate-600">
                <span className="font-semibold text-slate-700">Revision guidance:</span> {currentReviewTelemetry.critique}
              </div>
            )}
            {currentReviewTelemetry.fallbackStages.length > 0 && (
              <div className="mt-2 text-[11px] text-slate-500">
                Fallback stages: {currentReviewTelemetry.fallbackStages.join(', ')}
              </div>
            )}
          </div>
        )}
        {current && (
          <div className="mt-6 rounded-xl border border-slate-100 bg-slate-50 p-4">
            <div className="mb-2 text-[10px] font-bold uppercase tracking-widest text-slate-500">Chapter Goal</div>
            <ul className="list-inside list-disc space-y-1 text-xs leading-relaxed text-slate-600">
              {current.bullet_points.map((bp, i) => (
                <li key={i}>{bp}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
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
    <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 lg:grid-cols-5">
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm lg:col-span-3">
        <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-900 md:text-3xl">Publishing Desk</h2>
        <p className="mb-6 text-sm text-slate-500">{missing.length ? `${missing.length} chapters are incomplete; placeholders will be used.` : 'All chapters contain content.'}</p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <button
            onClick={() => doExport('pdf')}
            disabled={loading}
            className="flex items-center justify-center rounded-lg bg-rose-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Export PDF
          </button>
          <button
            onClick={() => doExport('docx')}
            disabled={loading}
            className="flex items-center justify-center rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Export DOCX
          </button>
          <button
            onClick={() => doExport('both')}
            disabled={loading}
            className="flex items-center justify-center rounded-lg bg-slate-900 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Export Both
          </button>
        </div>
      </div>
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm lg:col-span-2">
        <h3 className="mb-4 text-lg font-bold text-slate-900">Export Audit</h3>
        {missing.length ? (
          <ul className="list-inside list-disc space-y-1 text-sm text-slate-600">
            {missing.map((c) => (
              <li key={c.number}>
                {c.number}. {c.title}
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex items-center gap-2 text-sm font-medium text-emerald-600">
            <CheckCircle2 size={16} />
            No missing chapters. Ready to publish.
          </div>
        )}
      </div>
    </div>
  );
};

const InputGroup: React.FC<{
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  type?: 'text' | 'number';
  placeholder?: string;
  onBlur?: () => void;
  min?: number;
  step?: number;
  inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode'];
}> = ({ label, value, onChange, type = 'text', placeholder, onBlur, min, step, inputMode }) => (
  <div className="space-y-1.5">
    <label className="block text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</label>
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      placeholder={placeholder}
      min={min}
      step={step}
      inputMode={inputMode}
      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition-colors focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
    />
  </div>
);

const SelectGroup: React.FC<{ label: string; value: string; onChange: (v: string) => void; options: string[] }> = ({ label, value, onChange, options }) => (
  <div className="space-y-1.5">
    <label className="block text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</label>
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition-colors focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
    >
      {options.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  </div>
);

const TextAreaGroup: React.FC<{ label: string; value: string; onChange: (v: string) => void; placeholder?: string }> = ({ label, value, onChange, placeholder }) => (
  <div className="space-y-1.5">
    <label className="block text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</label>
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="min-h-[96px] w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition-colors focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
    />
  </div>
);

const MultiChoiceGroup: React.FC<{ label: string; options: string[]; values: string[]; onToggle: (value: string) => void }> = ({ label, options, values, onToggle }) => (
  <div>
    <label className="mb-2 block text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</label>
    <div className="flex flex-wrap gap-2">
      {options.map((option) => {
        const active = values.includes(option);
        return (
          <button
            key={option}
            type="button"
            onClick={() => onToggle(option)}
            className={`rounded-md border px-3 py-1.5 text-xs font-semibold shadow-sm transition-colors ${
              active
                ? 'border-indigo-600 bg-indigo-600 text-white'
                : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            {option}
          </button>
        );
      })}
    </div>
  </div>
);

export default BookStudioPage;
